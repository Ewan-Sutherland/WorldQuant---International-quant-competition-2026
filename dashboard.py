#!/usr/bin/env python3
"""Quick monitoring dashboard for the bot.
Run: python dashboard.py

Shows: eligible rate, submissions, epoch status, top families, self-corr stats.
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

# load environment
from dotenv import load_dotenv
load_dotenv()

from storage_supabase import Storage

def main():
    storage = Storage()
    owner = os.getenv("WQ_USERNAME", "unknown")

    print(f"\n{'='*70}")
    print(f"  ALPHABOT DASHBOARD - {owner}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*70}\n")

    # 1. recent runs summary
    try:
        runs = storage._get("runs", {
            "select": "family,template_id,sharpe,fitness,turnover,is_eligible,created_at",
            "order": "created_at.desc",
            "limit": "500",
        })
        if runs:
            total = len(runs)
            eligible = sum(1 for r in runs if r.get("is_eligible"))
            rate = eligible / total * 100 if total else 0

            # last 24h
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            recent = [r for r in runs if r.get("created_at", "") > cutoff]
            recent_eligible = sum(1 for r in recent if r.get("is_eligible"))
            recent_rate = recent_eligible / len(recent) * 100 if recent else 0

            print(f"  RUNS (last 500)")
            print(f"     Total: {total}  Eligible: {eligible} ({rate:.1f}%)")
            print(f"     Last 24h: {len(recent)} runs, {recent_eligible} eligible ({recent_rate:.1f}%)")

            # top families by eligible
            from collections import Counter
            fam_eligible = Counter()
            fam_total = Counter()
            for r in runs:
                fam = r.get("family", "unknown")
                fam_total[fam] += 1
                if r.get("is_eligible"):
                    fam_eligible[fam] += 1

            print(f"\n  TOP FAMILIES BY ELIGIBLE (last 500 runs)")
            for fam, count in fam_eligible.most_common(15):
                total_fam = fam_total[fam]
                pct = count / total_fam * 100
                avg_sharpe = sum(float(r.get("sharpe") or 0) for r in runs if r.get("family") == fam and r.get("is_eligible")) / max(count, 1)
                print(f"     {fam:40s} {count:3d}/{total_fam:3d} ({pct:4.0f}%)  avg_S={avg_sharpe:.2f}")
    except Exception as e:
        print(f"  ! Runs query failed: {e}")

    # 2. submissions
    print(f"\n  SUBMISSIONS")
    try:
        subs = storage._get("submissions", {
            "select": "submission_status,created_at,message",
            "order": "created_at.desc",
            "limit": "50",
        })
        if subs:
            confirmed = sum(1 for s in subs if s.get("submission_status") == "confirmed")
            rejected = sum(1 for s in subs if s.get("submission_status") == "rejected")
            print(f"     Last 50: {confirmed} confirmed, {rejected} rejected")

            # self-corr stats
            corr_fail = sum(1 for s in subs if "SELF_CORRELATION" in str(s.get("message", "")))
            corr_pass = confirmed  # confirmed = passed self-corr
            total_attempts = corr_fail + corr_pass
            pass_rate = corr_pass / total_attempts * 100 if total_attempts else 0
            print(f"     Self-corr: {corr_pass} pass / {corr_fail} fail ({pass_rate:.0f}% pass rate)")
        else:
            print(f"     No submissions found")
    except Exception as e:
        print(f"  ! Submissions query failed: {e}")

    # 3. ready alphas
    print(f"\n  READY ALPHAS")
    try:
        for check_owner in [owner, "teammate1@example.com", "teammate2@example.com", "teammate3@example.com"]:
            ready = storage._get("ready_alphas", {
                "select": "status,score_change,sharpe,family",
                "owner": f"eq.{check_owner}",
                "order": "score_change.desc.nullslast",
                "limit": "50",
            })
            if ready:
                positive = sum(1 for r in ready if r.get("score_change") is not None and r["score_change"] > 0)
                negative = sum(1 for r in ready if r.get("score_change") is not None and r["score_change"] < 0)
                unverified = sum(1 for r in ready if r.get("status") == "unverified")
                short_owner = check_owner.split("@")[0]
                print(f"     {short_owner:30s} +{positive} ready, -{negative} rejected, ?{unverified} unverified")
            else:
                short_owner = check_owner.split("@")[0]
                print(f"     {short_owner:30s} none")
    except Exception as e:
        print(f"  ! Ready alphas query failed: {e}")

    # 4. epoch status
    print(f"\n  EPOCH STATUS")
    try:
        bot_state = storage._get("bot_state", {
            "select": "config_snapshot,completion_count,updated_at",
            "owner": f"eq.{owner}",
            "limit": "1",
            "order": "updated_at.desc",
        })
        if bot_state:
            state = bot_state[0]
            completions = state.get("completion_count", 0)
            updated = state.get("updated_at", "")
            snapshot = state.get("config_snapshot")
            if snapshot:
                counters = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
                epoch = counters.get("epoch_state", {})
                cat_usage = counters.get("category_usage", {})

                epoch_idx = epoch.get("epoch_index", "?")
                epoch_gens = epoch.get("epoch_gen_count", 0)
                epoch_elig = epoch.get("epoch_eligible_count", 0)
                epoch_ext = epoch.get("epoch_extended", False)

                print(f"     Completions: {completions}  Updated: {updated}")
                print(f"     Epoch: {epoch_idx}  Gens: {epoch_gens}  Eligible: {epoch_elig}  Extended: {epoch_ext}")

                if cat_usage:
                    print(f"     Category usage:")
                    for cat, count in sorted(cat_usage.items(), key=lambda x: -x[1]):
                        if count > 0:
                            print(f"       {cat:30s} {count:4d}")
    except Exception as e:
        print(f"  ! Bot state query failed: {e}")

    print(f"\n{'='*70}\n")

if __name__ == "__main__":
    main()
