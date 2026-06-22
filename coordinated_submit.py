"""Coordinated team submission pipeline.

All participating bots check their own scores in parallel, then one coordinator
ranks globally and orchestrates submissions.

Signal protocol (via team_submit_signals table):
  - scores_ready:   "I've finished checking my own scores"
  - submit_command: "Submit this alpha" (target_owner + alpha_id + round_num)
  - submitted:      "I submitted (or failed)" (round_num + accepted)
  - recheck:        "Re-check your scores now" (round_num)
  - recheck_done:   "I've finished re-checking" (round_num)
  - done:           "Coordinator is finished, stop waiting"
"""

from __future__ import annotations
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import config


def _window_id() -> str:
    """Current submission window identifier.
    Uses 6-hour blocks aligned to 00:00 UTC so both bots always get the same ID
    even if they trigger a few minutes apart.
    """
    now = datetime.now(timezone.utc)
    block = (now.hour // 6) * 6
    return now.strftime(f"%Y-%m-%d") + f"T{block:02d}:00"


def _recent_cutoff() -> str:
    """ISO timestamp for recent coordination signals.

    Kept wider than the slowest expected score-check shard. Worker bots can emit
    scores_ready 20-30 minutes before the coordinator finishes its own checks; a
    per-bot run_started_at cutoff made those valid rows invisible. window_id
    already prevents cross-window leakage, so a generous same-window freshness
    guard is used instead.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    return cutoff.isoformat()


class CoordinatedSubmitPipeline:
    """Runs on every participating bot (coordinator + participants)."""

    WAIT_TIMEOUT = 7200  # 2 hours max wait for other bots. phase 1b sharding
                         # over large proxy pools (100+ alphas) can take 40+ min
                         # on the slowest shard, so the coordinator waits patiently.
    POLL_INTERVAL = 5    # seconds between polls

    def __init__(self, storage, client, config_mod):
        self.storage = storage
        self.client = client
        self.config = config_mod
        self.owner = storage.owner
        self.window_id = _window_id()
        self.is_coordinator = getattr(config_mod, "IS_COORDINATOR", False)
        self.participating_owners = getattr(config_mod, "COORDINATED_SUBMIT_OWNERS", [])
        # signal reads are keyed by the shared 6-hour window_id plus a generous
        # recent cutoff. don't use this bot's local start time for scores_ready;
        # slower coordinator runs can otherwise ignore valid worker signals that
        # arrived earlier in the same cycle.
        self.signal_cutoff = _recent_cutoff()

    # signals

    def _send_signal(self, signal: str, target_owner: str = None,
                     alpha_id: str = None, round_num: int = 0, payload: dict = None):
        """Write a coordination signal to Supabase. logs failures prominently -
        _post returns None on HTTP errors rather than raising, so check the return.
        """
        if payload is None:
            payload = {}
        payload["round_num"] = round_num
        try:
            result = self.storage._post("team_submit_signals", {
                "window_id": self.window_id,
                "owner": self.owner,
                "signal": signal,
                "target_owner": target_owner,
                "alpha_id": alpha_id,
                "payload": json.dumps(payload),
            })
            if result is None:
                print(f"  [SIGNAL] ! send returned None ({signal} -> {target_owner or 'all'}) - "
                      f"check team_submit_signals table exists in Supabase")
        except Exception as exc:
            print(f"  [SIGNAL] send failed ({signal}): {exc}")

    def _wait_for_signal(self, signal: str, from_owner: str = None,
                         target_owner: str = None, round_num: int = None,
                         timeout: int = None) -> dict | None:
        """Poll for a specific signal. Returns signal row or None on timeout.

        Uses a shared same-window freshness cutoff instead of this bot's local
        start time. this prevents the coordinator from missing workers that
        legitimately finished score checks earlier.
        """
        timeout = timeout or self.WAIT_TIMEOUT
        deadline = time.time() + timeout

        while time.time() < deadline:
            params = {
                "window_id": f"eq.{self.window_id}",
                "signal": f"eq.{signal}",
                "created_at": f"gte.{self.signal_cutoff}",
                "order": "created_at.desc",
                "limit": 10,
            }
            if from_owner:
                params["owner"] = f"eq.{from_owner}"
            if target_owner:
                params["target_owner"] = f"eq.{target_owner}"
            try:
                rows = self.storage._get("team_submit_signals", params)
                if rows and round_num is not None:
                    # filter by round_num in payload
                    for row in rows:
                        try:
                            p = json.loads(row.get("payload", "{}")) if row.get("payload") else {}
                        except (TypeError, json.JSONDecodeError):
                            p = {}
                        if p.get("round_num") == round_num:
                            return row
                elif rows:
                    return rows[0]
            except Exception as exc:
                print(f"  [SIGNAL] poll failed ({signal}): {exc}")
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(self.POLL_INTERVAL, remaining))
        return None

    # score checking

    def _check_own_scores(self) -> list[dict]:
        """Check scores for own ready_alphas using own credentials."""
        try:
            alphas = self.storage._get("ready_alphas", {
                "owner": f"eq.{self.owner}",
                "status": "in.(ready,unverified)",
                "select": "*",
                "order": "sharpe.desc",
            }) or []
        except Exception as exc:
            print(f"  ERROR loading own alphas: {exc}")
            return []

        if not alphas:
            print(f"  No ready alphas for {self.owner}")
            return []

        print(f"  Checking {len(alphas)} own alphas...")

        for i, a in enumerate(alphas):
            alpha_id = a.get("alpha_id")
            if not alpha_id:
                a["live_score"] = None
                continue

            score = None
            for attempt in range(3):
                try:
                    perf = self.client.check_before_after_performance(
                        alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                    )
                    score = perf.get("_score_change")
                    if score is not None:
                        break
                except Exception:
                    pass
                if attempt < 2:
                    time.sleep(3)

            a["live_score"] = score

            # write score to Supabase so the coordinator can read it.
            # use config.STAGING_FLOOR (-25) instead of a hardcoded -10, which used
            # to silently reject valid marginal alphas at score=-15..-25.
            try:
                _floor = getattr(self.config, "STAGING_FLOOR", -25)
                new_status = "ready" if score is not None and score >= 0 else (
                    "rejected" if score is not None and score < _floor else
                    "ready" if score is not None else "unverified"
                )
                self.storage._patch("ready_alphas", {"id": a["id"]}, {
                    "score_change": score,
                    "status": new_status,
                })
            except Exception:
                pass

            direction = "+" if score and score > 0 else "" if score else "?"
            print(f"    [{i+1}/{len(alphas)}] {a.get('family','')}/{a.get('template_id','')} "
                  f"S={a.get('sharpe',0):.2f} -> score: {direction}{score if score is not None else 'unknown'}")
            time.sleep(2)

        # retry unknowns once
        unknowns = [a for a in alphas if a.get("live_score") is None and a.get("alpha_id")]
        if unknowns:
            print(f"\n  {len(unknowns)} unknown - retrying after 10s...")
            time.sleep(10)
            for a in unknowns:
                try:
                    perf = self.client.check_before_after_performance(
                        a["alpha_id"], competition_id=self.config.IQC_COMPETITION_ID,
                    )
                    score = perf.get("_score_change")
                    if score is not None:
                        a["live_score"] = score
                        self.storage._patch("ready_alphas", {"id": a["id"]}, {
                            "score_change": score,
                            "status": "ready" if score >= getattr(self.config, "STAGING_FLOOR", -25) else "rejected",
                        })
                        print(f"    + {a.get('family','')} S={a.get('sharpe',0):.2f} -> {score:+.0f}")
                except Exception:
                    pass
                time.sleep(2)

        return alphas

    # main entry

    def run(self) -> dict:
        """Main entry - called by both coordinator and participants."""
        print(f"\n{'='*60}")
        print(f"  COORDINATED SUBMISSION - {self.owner}")
        print(f"  Window: {self.window_id}")
        print(f"  Role: {'COORDINATOR' if self.is_coordinator else 'PARTICIPANT'}")
        print(f"{'='*60}\n")

        # proxy score owners can't check their own scores - skip phase 1 and go
        # straight to a simple wait-for-done loop.
        proxy_owners = getattr(self.config, "PROXY_SCORE_OWNERS", [])
        if self.owner in proxy_owners:
            print("  -- Proxy mode: scores will be checked by coordinator --")
            self._send_signal("scores_ready", payload={
                "count": 0, "positive": 0, "proxy": True,
            })
            return self._run_proxy_wait()

        # phase 1: check own scores
        print("  -- Phase 1: Checking own scores --")
        alphas = self._check_own_scores()
        positive = [a for a in alphas if a.get("live_score") is not None and a["live_score"] > 0]
        print(f"\n  Own results: {len(positive)} positive out of {len(alphas)}\n")

        # phase 1b - each checker bot takes a shard of the proxy owner's alphas,
        # parallelizing what was previously sequential on the coordinator. a
        # 63-alpha re-sim took 2.5 hours solo; sharded across 3 bots = ~50 min each.
        # shards assigned by hash(alpha_id) % N so each alpha is checked by exactly one bot.
        checker_owners = [o for o in self.participating_owners if o not in proxy_owners]
        if self.owner in checker_owners and proxy_owners:
            my_shard_idx = checker_owners.index(self.owner)
            num_shards = len(checker_owners)
            for proxy in proxy_owners:
                if proxy in self.participating_owners:
                    print(f"\n  -- Phase 1b: Proxy shard {my_shard_idx + 1}/{num_shards} for {proxy} --")
                    self._check_proxy_scores_sharded(proxy, my_shard_idx, num_shards)

        # signal scores ready (after proxy sharding - so phase 2 won't start until all proxy work done)
        self._send_signal("scores_ready", payload={
            "count": len(alphas),
            "positive": len(positive),
        })

        if self.is_coordinator:
            return self._run_coordinator()
        else:
            return self._run_participant()

    # coordinator

    def _run_coordinator(self) -> dict:
        """Wait for all bots, rank globally, orchestrate submissions."""

        # phase 2: wait for other bots
        print("  -- Phase 2: Waiting for other bots --")
        other_owners = [o for o in self.participating_owners if o != self.owner]
        proxy_owners = set(getattr(self.config, "PROXY_SCORE_OWNERS", []))

        for other in other_owners:
            sig = self._wait_for_signal("scores_ready", from_owner=other)
            if sig:
                payload = json.loads(sig.get("payload", "{}")) if sig.get("payload") else {}
                if payload.get("proxy"):
                    print(f"    + {other}: proxy mode - will check scores now")
                else:
                    print(f"    + {other}: {payload.get('positive', '?')} positive ready")
            else:
                print(f"    ! {other}: timed out - proceeding without")

        # proxy scores already checked during phase 1b sharding (each checker bot
        # handled its shard in parallel). just proceed. the per-round recheck loop
        # below still updates the scores after each submission shifts the portfolio.

        # small delay to ensure DB writes have propagated
        time.sleep(3)

        # phase 3: greedy submission loop
        print("\n  -- Phase 3: Global ranking & submission --")
        submitted = 0
        rejected = 0
        max_rounds = getattr(self.config, "MAX_SUBMISSIONS_PER_WINDOW", 15)

        for round_num in range(1, max_rounds + 1):
            all_positive = self._read_all_positive()

            if not all_positive:
                print(f"\n  No more positive alphas - done")
                break

            best = all_positive[0]
            best_owner = best["_owner"]
            best_score = best.get("score_change", 0)
            best_alpha_id = best.get("alpha_id", "")

            print(f"\n  * Round {round_num}: BEST = {best_owner} "
                  f"score={best_score:+.0f} S={best.get('sharpe',0):.2f} "
                  f"{best.get('family','')}")

            if best_owner == self.owner:
                # submit directly
                print(f"  Submitting own alpha...")
                success = self._submit_alpha(best)
            else:
                # tell the other bot to submit
                print(f"  Sending submit command to {best_owner}...")
                self._send_signal("submit_command",
                                  target_owner=best_owner,
                                  alpha_id=best_alpha_id,
                                  round_num=round_num,
                                  payload={"score": best_score})

                # wait for response (keyed by round_num - no replay bug)
                sig = self._wait_for_signal("submitted", from_owner=best_owner,
                                            round_num=round_num, timeout=120)
                if sig:
                    p = json.loads(sig.get("payload", "{}")) if sig.get("payload") else {}
                    success = p.get("accepted", False)
                    if success:
                        print(f"    + {best_owner} ACCEPTED")
                    else:
                        print(f"    x {best_owner} rejected: {p.get('reason', 'unknown')}")
                else:
                    print(f"    ! {best_owner} didn't respond - skipping this alpha")
                    success = False

            if success:
                submitted += 1
            else:
                rejected += 1
                try:
                    self.storage._patch("ready_alphas", {"id": best["id"]}, {"status": "rejected"})
                except Exception:
                    pass

            # only re-check scores if we actually submitted something. if the
            # submission failed (self-correlation, CW, etc.), nothing hit the WQ
            # portfolio so scores are still accurate. skipping here saves ~40-60s
            # per failed round across all bots and avoids pointless API calls.
            if success:
                print(f"  Re-checking scores after round {round_num}...")
                self._send_signal("recheck", round_num=round_num)
                self._recheck_own_positive()

                # also recheck proxy owners' scores (portfolio shifted)
                for proxy in proxy_owners:
                    if proxy in [o for o in self.participating_owners]:
                        self._recheck_proxy_scores(proxy)

                # wait for other bots to finish rechecking. _recheck_own_positive
                # takes ~2s/alpha x ~20 alphas = ~40-60s per bot, so 180s gives
                # comfortable margin even with slow API.
                for other in other_owners:
                    self._wait_for_signal("recheck_done", from_owner=other,
                                          round_num=round_num, timeout=180)
                time.sleep(2)
            else:
                print(f"  Skipping recheck (submission failed, no portfolio shift)")
                time.sleep(1)

        # signal done so participants stop waiting
        self._send_signal("done")

        print(f"\n{'='*60}")
        print(f"  COORDINATED SUBMISSION COMPLETE")
        print(f"  Submitted: {submitted}  Rejected: {rejected}")
        print(f"{'='*60}\n")

        return {"submitted": submitted, "rejected": rejected}

    # participant

    def _run_proxy_wait(self) -> dict:
        """Dead-simple wait loop for proxy owners.

        Waits until the coordinator sends 'done'. no round counter, no deadlines,
        no silence detection. just polls for submit_command / recheck / done and
        reacts as things arrive. keeps the proxy bot blocked in the tick loop until
        the submission window is officially closed. monitored externally for stalls.
        """
        submitted = 0
        rejected = 0
        seen_submit_cmds = set()   # alpha_ids we've already submitted
        seen_rechecks = set()      # round_nums we've already ack'd

        print("  -- Waiting for coordinator (no timeout) --")

        while True:
            # check for done - coordinator explicitly said to stop
            done_sig = self._wait_for_signal("done", timeout=1)
            if done_sig:
                print("  Coordinator finished - done")
                break

            # check for submit command (any round_num, filtered by alpha_id we haven't done)
            cmd_sig = self._wait_for_signal("submit_command",
                                             target_owner=self.owner,
                                             timeout=1)
            if cmd_sig:
                alpha_id = cmd_sig.get("alpha_id")
                if alpha_id and alpha_id not in seen_submit_cmds:
                    seen_submit_cmds.add(alpha_id)
                    payload = json.loads(cmd_sig.get("payload", "{}")) if cmd_sig.get("payload") else {}
                    round_num = payload.get("round_num", 0)
                    print(f"\n  > Round {round_num}: submit alpha_id={alpha_id[:12]}... "
                          f"(score={payload.get('score', '?')})")

                    # find the alpha
                    try:
                        rows = self.storage._get("ready_alphas", {
                            "owner": f"eq.{self.owner}",
                            "alpha_id": f"eq.{alpha_id}",
                        }) or []
                    except Exception:
                        rows = []

                    if not rows:
                        print(f"  ! Alpha not found - skipping")
                        self._send_signal("submitted", round_num=round_num,
                                          payload={"accepted": False, "reason": "not_found"})
                        rejected += 1
                    else:
                        alpha = rows[0]
                        success = self._submit_alpha(alpha)
                        if success:
                            submitted += 1
                            self._send_signal("submitted", round_num=round_num,
                                              payload={"accepted": True, "alpha_id": alpha_id})
                        else:
                            rejected += 1
                            self._send_signal("submitted", round_num=round_num,
                                              payload={"accepted": False, "alpha_id": alpha_id,
                                                       "reason": "rejected"})
                            try:
                                self.storage._patch("ready_alphas", {"id": alpha["id"]},
                                                    {"status": "rejected"})
                            except Exception:
                                pass
                    # fall through to keep polling

            # check for recheck (coordinator submitted something, tell us to re-check).
            # for proxy owners, the coordinator handles the actual re-check; we just ack.
            recheck_sig = self._wait_for_signal("recheck", timeout=1)
            if recheck_sig:
                payload = json.loads(recheck_sig.get("payload", "{}")) if recheck_sig.get("payload") else {}
                round_num = payload.get("round_num", 0)
                if round_num and round_num not in seen_rechecks:
                    seen_rechecks.add(round_num)
                    self._send_signal("recheck_done", round_num=round_num)

            time.sleep(self.POLL_INTERVAL)

        print(f"\n  Proxy wait done: submitted={submitted} rejected={rejected}")
        return {"submitted": submitted, "rejected": rejected}

    def _run_participant(self) -> dict:
        """Wait for coordinator commands, submit when told. no internal timeouts -
        loop blocks until the coordinator sends 'done'. same pattern as proxy wait but
        also runs _recheck_own_positive() on recheck signals so participant bots keep
        their own alpha scores fresh after each submission shifts the portfolio.
        monitored externally for stalls.
        """
        submitted = 0
        rejected = 0
        seen_submit_cmds = set()   # alpha_ids already processed
        seen_rechecks = set()      # round_nums already acknowledged

        print("  -- Waiting for coordinator (no timeout) --")

        while True:
            # check for done
            done_sig = self._wait_for_signal("done", timeout=1)
            if done_sig:
                print("  Coordinator finished - done")
                break

            # check for submit command targeted at us (any round)
            cmd_sig = self._wait_for_signal("submit_command",
                                             target_owner=self.owner,
                                             timeout=1)
            if cmd_sig:
                alpha_id = cmd_sig.get("alpha_id")
                if alpha_id and alpha_id not in seen_submit_cmds:
                    seen_submit_cmds.add(alpha_id)
                    payload = json.loads(cmd_sig.get("payload", "{}")) if cmd_sig.get("payload") else {}
                    round_num = payload.get("round_num", 0)
                    print(f"\n  > Round {round_num}: submit alpha_id={alpha_id[:12]}... "
                          f"(score={payload.get('score', '?')})")

                    try:
                        rows = self.storage._get("ready_alphas", {
                            "owner": f"eq.{self.owner}",
                            "alpha_id": f"eq.{alpha_id}",
                        }) or []
                    except Exception:
                        rows = []

                    if not rows:
                        print(f"  ! Alpha not found - skipping")
                        self._send_signal("submitted", round_num=round_num,
                                          payload={"accepted": False, "reason": "not_found"})
                        rejected += 1
                    else:
                        alpha = rows[0]
                        success = self._submit_alpha(alpha)
                        if success:
                            submitted += 1
                            self._send_signal("submitted", round_num=round_num,
                                              payload={"accepted": True, "alpha_id": alpha_id})
                        else:
                            rejected += 1
                            self._send_signal("submitted", round_num=round_num,
                                              payload={"accepted": False, "alpha_id": alpha_id,
                                                       "reason": "rejected"})
                            try:
                                self.storage._patch("ready_alphas", {"id": alpha["id"]},
                                                    {"status": "rejected"})
                            except Exception:
                                pass

            # check for recheck - refresh our own alpha scores
            recheck_sig = self._wait_for_signal("recheck", timeout=1)
            if recheck_sig:
                payload = json.loads(recheck_sig.get("payload", "{}")) if recheck_sig.get("payload") else {}
                round_num = payload.get("round_num", 0)
                if round_num and round_num not in seen_rechecks:
                    seen_rechecks.add(round_num)
                    print(f"  Round {round_num}: coordinator submitted - re-checking own scores...")
                    self._recheck_own_positive()
                    self._send_signal("recheck_done", round_num=round_num)

            time.sleep(self.POLL_INTERVAL)

        print(f"\n  Participant done: submitted={submitted} rejected={rejected}")
        return {"submitted": submitted, "rejected": rejected}

    # helpers

    def _read_all_positive(self) -> list[dict]:
        """Read all positive ready_alphas across participating owners, sorted by rank.

        Ranking order (all DESC except noted):
          1. score_change - highest portfolio impact first
          2. fitness      - more robust to future portfolio shifts
          3. sharpe ASC   - lower sharpe = more unique PnL curve, less likely to
                            block future alphas via self-corr
        Tie on all three: stable sort falls back to Supabase's return order.
        """
        all_positive = []
        for owner in self.participating_owners:
            try:
                min_score = getattr(self.config, "SUBMIT_MIN_SCORE", 15)
                rows = self.storage._get("ready_alphas", {
                    "owner": f"eq.{owner}",
                    "status": "eq.ready",
                    "score_change": f"gte.{min_score}",
                    "order": "score_change.desc",
                }) or []
                for r in rows:
                    r["_owner"] = owner
                    all_positive.append(r)
            except Exception as exc:
                print(f"    ERROR reading {owner}: {exc}")

        def sort_key(x):
            return (
                -round(x.get("score_change") or 0, 0),   # higher score first (round to tier)
                -round(x.get("fitness") or 0, 2),        # higher fitness first
                round(x.get("sharpe") or 0, 2),          # lower sharpe first
            )

        all_positive.sort(key=sort_key)
        return all_positive

    def _submit_alpha(self, alpha: dict) -> bool:
        """Submit a single alpha to WQ. Returns True if accepted.

        Defense-in-depth score guard. callers also filter by score >=
        SUBMIT_MIN_SCORE, but this is the final boundary before a WQ submission.
        if a participant receives a stale submit_command from the coordinator (or
        any other code path slips through), this guard prevents a negative-score
        alpha from ever reaching WQ.
        """
        alpha_id = alpha.get("alpha_id")
        if not alpha_id:
            return False

        # hard score floor - never submit anything below SUBMIT_MIN_SCORE.
        # single source of truth from config so the rule can be tuned in one place.
        min_score = getattr(self.config, "SUBMIT_MIN_SCORE", 15)
        score = alpha.get("score_change")
        if score is None or float(score) < min_score:
            print(
                f"    [SCORE_GUARD] Refusing to submit alpha_id={alpha_id} "
                f"score={score} < min_score={min_score} "
                f"(family={alpha.get('family','?')})"
            )
            return False

        try:
            result = self.client.submit_alpha(alpha_id)
        except Exception as exc:
            print(f"    Submit error: {exc}")
            return False

        accepted = result.get("_accepted")
        if accepted:
            # update ready_alphas status
            try:
                self.storage._patch("ready_alphas", {"id": alpha["id"]}, {"status": "submitted"})
            except Exception:
                pass
            # insert into submissions table (was missing - only ready_alphas was
            # patched, so warm-start never loaded these as passed cores and the
            # universe sweeper never queued them)
            try:
                from models import new_id, utc_now
                self.storage.insert_submission(
                    submission_id=new_id("sub"),
                    candidate_id=alpha.get("candidate_id", ""),
                    run_id=alpha.get("run_id", ""),
                    submitted_at=utc_now(),
                    submission_status="confirmed",
                    message=f"coordinated_submit: score={alpha.get('score_change', '?')} "
                            f"S={alpha.get('sharpe', 0):.2f} F={alpha.get('fitness', 0):.2f} "
                            f"owner={alpha.get('_owner', self.owner)}",
                )
            except Exception as exc:
                print(f"    ! insert_submission failed (alpha IS on WQ): {exc}")
            print(f"    + ACCEPTED - score {alpha.get('score_change', '?')}")
            return True
        else:
            reason = result.get("_fail_reason", "unknown")
            corr = result.get("_self_correlation")
            # insert rejected submissions into the submissions table too. was
            # missing - warm-start couldn't learn that this core had been rejected,
            # so the bot would re-attempt the same core after restart. update
            # ready_alphas status to 'rejected' so we don't retry in this run.
            try:
                self.storage._patch("ready_alphas", {"id": alpha["id"]}, {"status": "rejected"})
            except Exception:
                pass
            try:
                from models import new_id, utc_now
                self.storage.insert_submission(
                    submission_id=new_id("sub"),
                    candidate_id=alpha.get("candidate_id", ""),
                    run_id=alpha.get("run_id", ""),
                    submitted_at=utc_now(),
                    submission_status="rejected",
                    message=f"rejected at submit: {reason}" + (f" (corr={corr})" if corr else ""),
                )
            except Exception as exc:
                print(f"    ! insert_submission (rejected) failed: {exc}")
            print(f"    x Rejected: {reason}" + (f" (corr={corr})" if corr else ""))
            return False

    def _recheck_own_positive(self):
        """Quick re-check of own positive alphas after a team submission."""
        try:
            rows = self.storage._get("ready_alphas", {
                "owner": f"eq.{self.owner}",
                "status": "eq.ready",
                "order": "score_change.desc",
            }) or []
        except Exception:
            return

        for a in rows:
            alpha_id = a.get("alpha_id")
            if not alpha_id:
                continue
            try:
                perf = self.client.check_before_after_performance(
                    alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                )
                score = perf.get("_score_change")
                if score is not None:
                    # use config.STAGING_FLOOR (-25) not a hardcoded -10
                    _floor = getattr(self.config, "STAGING_FLOOR", -25)
                    self.storage._patch("ready_alphas", {"id": a["id"]}, {
                        "score_change": score,
                        "status": "ready" if score >= _floor else "rejected",
                    })
                    direction = "+" if score > 0 else ""
                    print(f"    {a.get('family','')}/{a.get('template_id','')} "
                          f"S={a.get('sharpe',0):.2f} -> {direction}{score:.0f}")
            except Exception:
                pass
            time.sleep(2)

    def _check_proxy_scores_sharded(self, proxy_owner: str, shard_idx: int, num_shards: int) -> None:
        """Check scores for a proxy owner's alphas - but only for this bot's shard.

        Sharding by hash(alpha_id) % num_shards ensures each alpha is checked by
        exactly one bot. all bots run in parallel during phase 1b, splitting the
        total re-sim work ~N-way. results written to ready_alphas (keeping
        proxy_owner as owner). also records the coordinator alpha_id -> original
        alpha_id mapping so any bot can re-check later using that.
        """
        try:
            alphas = self.storage._get("ready_alphas", {
                "owner": f"eq.{proxy_owner}",
                "status": "in.(ready,unverified)",
                "select": "*",
                "order": "sharpe.desc",
            }) or []
        except Exception as exc:
            print(f"    ERROR loading {proxy_owner} alphas: {exc}")
            return

        if not alphas:
            print(f"    No ready/unverified alphas for {proxy_owner}")
            return

        # filter to just this bot's shard. use hashlib.md5 for a stable hash -
        # Python's built-in hash() is randomized per-process, so each bot would get
        # different shard assignments and alphas would be checked 0x or 2x.
        import hashlib
        def stable_shard(alpha_id: str) -> int:
            if not alpha_id:
                return 0
            return int(hashlib.md5(alpha_id.encode()).hexdigest(), 16) % num_shards
        my_alphas = [a for a in alphas if stable_shard(a.get("alpha_id", "")) == shard_idx]
        print(f"    Shard {shard_idx + 1}/{num_shards}: {len(my_alphas)} of {len(alphas)} alphas")

        # track coordinator alpha_ids for rechecks later (in-memory this session)
        if not hasattr(self, "_proxy_alpha_map"):
            self._proxy_alpha_map = {}

        # process 2 alphas concurrently per bot for speed. each bot has 3 sim slots -
        # using 2 leaves 1 free for safety. sharded across 3 bots x 2 concurrent =
        # 6x speedup vs the original sequential approach.
        BATCH = 2
        idx = 0
        while idx < len(my_alphas):
            batch = my_alphas[idx:idx + BATCH]
            idx += BATCH

            # step 1: submit all sims in this batch
            in_flight = []  # (alpha, sim_id)
            for a in batch:
                expr = a.get("expression", "")
                settings_raw = a.get("settings_json", "{}")
                if not expr:
                    continue
                if isinstance(settings_raw, str):
                    try:
                        settings = json.loads(settings_raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                else:
                    settings = settings_raw or {}
                if not settings:
                    continue

                try:
                    sim_id = self.client.submit_simulation(expr, settings)
                    in_flight.append((a, sim_id))
                except Exception as exc:
                    if "429" in str(exc) or "CONCURRENT" in str(exc).upper():
                        time.sleep(10)
                        try:
                            sim_id = self.client.submit_simulation(expr, settings)
                            in_flight.append((a, sim_id))
                        except Exception:
                            continue

            if not in_flight:
                continue

            # step 2: poll all sims in batch until complete
            results = {}  # sim_id -> result
            deadline = time.time() + 300  # 5 min per batch
            while len(results) < len(in_flight) and time.time() < deadline:
                for a, sid in in_flight:
                    if sid in results:
                        continue
                    try:
                        r = self.client.poll_simulation(sid)
                        if r.get("status") in ("completed", "failed", "timed_out"):
                            results[sid] = r
                    except Exception:
                        pass
                if len(results) < len(in_flight):
                    time.sleep(5)

            # step 3: for each result, check before-after score
            for batch_idx, (a, sid) in enumerate(in_flight):
                global_i = idx - len(batch) + batch_idx

                if sid not in results or results[sid].get("status") != "completed":
                    print(f"    [{global_i+1}/{len(my_alphas)}] ~ {a.get('family','')} "
                          f"S={a.get('sharpe',0):.2f} - sim timeout")
                    continue

                # get this bot's alpha_id from the re-sim
                check_alpha_id = None
                try:
                    raw = results[sid].get("alpha_id", "")
                    if raw:
                        check_alpha_id = str(raw).rstrip("/").split("/")[-1]
                except Exception:
                    pass

                if not check_alpha_id:
                    continue

                # store mapping
                proxy_alpha_id = a.get("alpha_id", "")
                if proxy_alpha_id:
                    self._proxy_alpha_map[proxy_alpha_id] = check_alpha_id

                # check before-after score
                score = None
                for attempt in range(2):
                    try:
                        perf = self.client.check_before_after_performance(
                            check_alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                        )
                        score = perf.get("_score_change")
                        if score is not None:
                            break
                    except Exception:
                        pass
                    if attempt < 1:
                        time.sleep(3)

                if score is not None:
                    direction = "+" if score > 0 else "-" if score < 0 else "="
                    print(f"    [{global_i+1}/{len(my_alphas)}] {direction} {a.get('family','')} "
                          f"S={a.get('sharpe',0):.2f} -> {score:+.0f}")
                    # write core data (score + status) first - MUST succeed.
                    # check_alpha_id column may not exist, so patch it separately.
                    self.storage._patch("ready_alphas", {"id": a["id"]}, {
                        "score_change": score,
                        "status": "ready" if score >= getattr(self.config, "STAGING_FLOOR", -25) else "rejected",
                    })
                    # separately try to persist check_alpha_id for cross-shard rechecks.
                    # if the column doesn't exist, _patch returns None silently -
                    # rechecks then fall back to the in-memory _proxy_alpha_map.
                    try:
                        self.storage._patch("ready_alphas", {"id": a["id"]}, {
                            "check_alpha_id": check_alpha_id,
                        })
                    except Exception:
                        pass
                else:
                    print(f"    [{global_i+1}/{len(my_alphas)}] ? {a.get('family','')} "
                          f"S={a.get('sharpe',0):.2f} -> score unavailable")

            time.sleep(2)

    def _check_proxy_scores(self, proxy_owner: str) -> None:
        """Check scores for a proxy owner by re-simulating through the coordinator's credentials.

        A proxy owner can't check their own scores. the coordinator re-simulates
        their expressions, gets fresh alpha_ids, and checks before-after scores.
        results are written back to ready_alphas (keeping the proxy owner as owner).
        """
        try:
            alphas = self.storage._get("ready_alphas", {
                "owner": f"eq.{proxy_owner}",
                "status": "in.(ready,unverified)",
                "select": "*",
                "order": "sharpe.desc",
            }) or []
        except Exception as exc:
            print(f"    ERROR loading {proxy_owner} alphas: {exc}")
            return

        if not alphas:
            print(f"    No ready/unverified alphas for {proxy_owner}")
            return

        print(f"    Checking {len(alphas)} alphas for {proxy_owner}...")

        # track coordinator alpha_ids for rechecks later
        if not hasattr(self, "_proxy_alpha_map"):
            self._proxy_alpha_map = {}

        for i, a in enumerate(alphas):
            expr = a.get("expression", "")
            settings_raw = a.get("settings_json", "{}")

            if not expr:
                continue

            if isinstance(settings_raw, str):
                try:
                    settings = json.loads(settings_raw)
                except (json.JSONDecodeError, TypeError):
                    continue
            else:
                settings = settings_raw or {}

            if not settings:
                continue

            # re-simulate through the coordinator's credentials
            try:
                sim_id = self.client.submit_simulation(expr, settings)
            except Exception as exc:
                if "429" in str(exc) or "CONCURRENT" in str(exc).upper():
                    time.sleep(10)
                    try:
                        sim_id = self.client.submit_simulation(expr, settings)
                    except Exception:
                        continue
                else:
                    continue

            # poll for completion
            deadline = time.time() + 180
            result = None
            while time.time() < deadline:
                try:
                    r = self.client.poll_simulation(sim_id)
                    if r.get("status") in ("completed", "failed", "timed_out"):
                        result = r
                        break
                except Exception:
                    pass
                time.sleep(5)

            if not result or result.get("status") != "completed":
                continue

            # get the coordinator's alpha_id
            coord_alpha_id = None
            try:
                raw = result.get("alpha_id", "")
                if raw:
                    coord_alpha_id = str(raw).rstrip("/").split("/")[-1]
            except Exception:
                pass

            if not coord_alpha_id:
                continue

            # store mapping for rechecks
            proxy_alpha_id = a.get("alpha_id", "")
            if proxy_alpha_id:
                self._proxy_alpha_map[proxy_alpha_id] = coord_alpha_id

            # check before-after score
            score = None
            for attempt in range(2):
                try:
                    perf = self.client.check_before_after_performance(
                        coord_alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                    )
                    score = perf.get("_score_change")
                    if score is not None:
                        break
                except Exception:
                    pass
                if attempt < 1:
                    time.sleep(3)

            if score is not None:
                direction = "+" if score > 0 else "-" if score < 0 else "="
                print(f"    [{i+1}/{len(alphas)}] {direction} {a.get('family','')} "
                      f"S={a.get('sharpe',0):.2f} -> {score:+.0f}")
                try:
                    self.storage._patch("ready_alphas", {"id": a["id"]}, {
                        "score_change": score,
                        "status": "ready" if score >= getattr(self.config, "STAGING_FLOOR", -25) else "rejected",
                    })
                except Exception:
                    pass
            else:
                print(f"    [{i+1}/{len(alphas)}] ? {a.get('family','')} "
                      f"S={a.get('sharpe',0):.2f} -> score unavailable")

            time.sleep(2)

    def _recheck_proxy_scores(self, proxy_owner: str) -> None:
        """Quick re-check of a proxy owner's positive alphas.

        Uses check_alpha_id (persisted by any bot's shard in phase 1b) so the
        coordinator can recheck all sharded alphas - not just the ones from its own
        shard. falls back to the in-memory _proxy_alpha_map if the column is missing.
        only rechecks status='ready' alphas. rejected alphas stay rejected.
        """
        proxy_map = getattr(self, "_proxy_alpha_map", {})

        try:
            rows = self.storage._get("ready_alphas", {
                "owner": f"eq.{proxy_owner}",
                "status": "eq.ready",
                "order": "score_change.desc",
            }) or []
        except Exception:
            return

        for a in rows:
            # prefer persisted check_alpha_id from DB (works across all bots' shards)
            check_alpha_id = a.get("check_alpha_id")
            if not check_alpha_id:
                # fallback: in-memory map (only has this coordinator's shard)
                check_alpha_id = proxy_map.get(a.get("alpha_id", ""))
            if not check_alpha_id:
                continue
            try:
                perf = self.client.check_before_after_performance(
                    check_alpha_id, competition_id=self.config.IQC_COMPETITION_ID,
                )
                score = perf.get("_score_change")
                if score is not None:
                    self.storage._patch("ready_alphas", {"id": a["id"]}, {
                        "score_change": score,
                        "status": "ready" if score >= getattr(self.config, "STAGING_FLOOR", -25) else "rejected",
                    })
                    direction = "+" if score > 0 else ""
                    print(f"    [proxy] {a.get('family','')}/{a.get('template_id','')} "
                          f"S={a.get('sharpe',0):.2f} -> {direction}{score:.0f}")
            except Exception:
                pass
            time.sleep(2)
