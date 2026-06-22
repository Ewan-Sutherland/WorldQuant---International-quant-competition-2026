from __future__ import annotations

import json
import signal
import sys
import time

import config
from bot import AlphaBot
from brain_client import BrainClient
from generator import AlphaGenerator
from scheduler import Scheduler
from storage_factory import get_storage


def main() -> None:
    storage = get_storage()
    generator = AlphaGenerator()
    scheduler = Scheduler(max_slots=config.MAX_CONCURRENT_SIMS)

    client = BrainClient(
        username=config.BRAIN_USERNAME,
        password=config.BRAIN_PASSWORD,
        base_url="https://api.worldquantbrain.com",
    )

    bot = AlphaBot(
        storage=storage,
        client=client,
        generator=generator,
        scheduler=scheduler,
    )

    # graceful shutdown: first Ctrl+C finishes the current tick and saves, second forces exit
    shutdown_requested = False

    def handle_shutdown(signum, frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            print("\n[FORCE_STOP] Second signal - exiting immediately")
            sys.exit(1)
        shutdown_requested = True
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else signum
        print(f"\n[SHUTDOWN] {sig_name} received - finishing current tick, then saving state...")

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # recover anything left running or stale from the previous session
    bot.recover_running_from_storage()
    bot.mark_stale_runs_timed_out()

    # re-queue refinements that a previous shutdown interrupted mid-flight
    try:
        bot_state = storage.get_bot_state()
        if bot_state and bot_state.get("status") == "interrupted":
            interrupted_refs = bot_state.get("interrupted_refinement_ids")
            if interrupted_refs:
                ids = json.loads(interrupted_refs) if isinstance(interrupted_refs, str) else (interrupted_refs or [])
                for cid in ids:
                    try:
                        storage.un_consume_refinement(cid)
                        print(f"[RESUME] Re-queued interrupted refinement: {cid[:20]}...")
                    except Exception as e:
                        print(f"[RESUME_WARN] Could not re-queue {cid[:20]}: {e}")
                if ids:
                    print(f"[RESUME] Re-queued {len(ids)} interrupted refinements")
    except Exception as e:
        print(f"[RESUME_WARN] Could not load bot state: {e}")

    # mark ourselves as running
    try:
        storage.save_bot_state(status="running", completion_count=0)
    except Exception:
        pass

    # print the available-field summary on startup
    try:
        from datasets import print_dataset_summary
        print_dataset_summary()
    except Exception as e:
        print(f"[DATASETS_WARN] {e}")

    print("[START] Alpha bot is running")
    print(f"[START] Owner: {storage.owner}")
    print(f"[START] Press Ctrl+C once for graceful shutdown, twice to force quit")

    # main loop
    tick_count = 0

    while not shutdown_requested:
        try:
            bot.tick()
            tick_count += 1

            # heartbeat every 10 ticks
            if tick_count % 10 == 0:
                try:
                    storage.heartbeat()
                except Exception:
                    pass

        except KeyboardInterrupt:
            handle_shutdown(signal.SIGINT, None)
            break
        except Exception as exc:
            print(f"[MAIN_LOOP_ERROR] {exc}")

        time.sleep(config.POLL_INTERVAL_SECONDS)

    # shutdown: save state so the next run can resume where this one stopped
    print("[SHUTDOWN] Saving state...")

    # mark in-flight sims as interrupted
    in_flight_runs = []
    try:
        running = storage.get_running_runs()
        in_flight_runs = [r["run_id"] for r in running]
        if in_flight_runs:
            storage.mark_runs_interrupted(in_flight_runs)
            print(f"[SHUTDOWN] Marked {len(in_flight_runs)} in-flight runs as interrupted")
    except Exception as e:
        print(f"[SHUTDOWN_WARN] Could not mark in-flight runs: {e}")

    # remember which candidates were mid-refinement
    mid_refinement_ids = list(getattr(bot, "_active_refinement_ids", set()))

    # publish final family/template stats for the rest of the team
    try:
        if hasattr(bot, "team_weights") and bot.team_weights:
            bot.team_weights.publish_own_stats()
            print("[SHUTDOWN] Published final team stats")
    except Exception as e:
        print(f"[SHUTDOWN_WARN] Could not publish team stats: {e}")

    # save bot state, refinement counters and blocked cores so the next run skips redone work
    try:
        refinement_counters = {
            "refinement_attempts_by_base": getattr(bot, "refinement_attempts_by_base", {}),
            "refinement_attempts_by_core": getattr(bot, "refinement_attempts_by_core", {}),
            "core_signal_exhausted": getattr(bot, "core_signal_exhausted", {}),
            "family_template_exhausted": getattr(bot, "family_template_exhausted", {}),
            "score_negative_cores": list(getattr(bot, "_score_negative_cores", set())),
            "swept_keys": list(getattr(bot.universe_sweeper, "_swept", set())) if hasattr(bot, "universe_sweeper") else [],
        }
        storage.save_bot_state(
            status="interrupted" if (in_flight_runs or mid_refinement_ids) else "stopped",
            completion_count=getattr(bot, "total_completions", 0),
            interrupted_refinement_ids=mid_refinement_ids,
            refinement_counters=refinement_counters,
        )
        n_swept = len(refinement_counters.get("swept_keys", []))
        n_blocked = len(refinement_counters.get("score_negative_cores", []))
        print(f"[SHUTDOWN] Bot state saved (completions={getattr(bot, 'total_completions', 0)}, "
              f"refinement_counters={sum(len(v) for v in refinement_counters.values() if isinstance(v, dict))} entries, "
              f"swept={n_swept}, blocked_cores={n_blocked})")
    except Exception as e:
        print(f"[SHUTDOWN_WARN] Could not save bot state: {e}")

    print("[STOP] Shutdown complete")


if __name__ == "__main__":
    main()
