from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

import config


class BrainAPIError(Exception):
    pass


class BrainAuthError(BrainAPIError):
    pass


class BrainClient:
    """
    WorldQuant BRAIN API client.

    submit_simulation() is non-blocking - polling is done separately by the
    bot/scheduler. Internal settings use snake_case; the API wants camelCase,
    so the payload builder maps between them.
    """

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str,
        login_path: str = "/authentication",
        simulation_path: str = "/simulations",
        timeout_seconds: int = 30,
    ):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.login_path = login_path
        self.simulation_path = simulation_path
        self.timeout_seconds = timeout_seconds

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json;version=2.0",
                "Content-Type": "application/json",
            }
        )

        self.last_auth_time: Optional[datetime] = None

    def login(self) -> None:
        if not self.username or not self.password:
            raise BrainAuthError(
                "Missing BRAIN_USERNAME or BRAIN_PASSWORD environment variables."
            )

        url = f"{self.base_url}{self.login_path}"

        response = self.session.post(
            url,
            auth=(self.username, self.password),
            timeout=self.timeout_seconds,
        )

        if response.status_code not in (200, 201, 204):
            raise BrainAuthError(
                f"Login failed with status {response.status_code}: {response.text}"
            )

        self.last_auth_time = datetime.now(timezone.utc)

    def ensure_session(self) -> None:
        if self.last_auth_time is None:
            self.login()
            return

        age = datetime.now(timezone.utc) - self.last_auth_time
        if age > timedelta(minutes=config.SESSION_REFRESH_MINUTES):
            self.login()

    def submit_simulation(self, expression: str, settings: dict[str, Any]) -> str:
        """
        Submit a simulation and return its id or progress URL. Does not block.
        """
        self.ensure_session()

        url = f"{self.base_url}{self.simulation_path}"
        payload = self._build_simulation_payload(expression, settings)

        response = self.session.post(
            url,
            json=payload,
            timeout=self.timeout_seconds,
        )

        if response.status_code == 401:
            self.login()
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout_seconds,
            )

        if response.status_code not in (200, 201, 202):
            raise BrainAPIError(
                f"Simulation submit failed with status {response.status_code}: {response.text}"
            )

        sim_id = self._extract_simulation_id(response)
        if not sim_id:
            raise BrainAPIError(
                "Simulation submission succeeded but no simulation id could be extracted."
            )

        return sim_id

    def poll_simulation(self, sim_id: str) -> dict[str, Any]:
        """
        Poll a simulation by id/url and return a normalised result dict that
        always includes status and raw.
        """
        self.ensure_session()

        url = self._simulation_status_url(sim_id)
        response = self.session.get(url, timeout=self.timeout_seconds)

        if response.status_code == 401:
            self.login()
            response = self.session.get(url, timeout=self.timeout_seconds)

        if response.status_code != 200:
            raise BrainAPIError(
                f"Polling failed for sim_id={sim_id} with status {response.status_code}: {response.text}"
            )

        raw = self._parse_json(response)
        status = self._extract_status(raw)

        result = {
            "status": status,
            "raw": raw,
        }

        if status == "completed":
            alpha_id = raw.get("alpha")
            result["alpha_id"] = alpha_id

            if alpha_id:
                try:
                    alpha_data = self.get_alpha(alpha_id)
                    result["alpha_data"] = alpha_data
                    result.update(self._extract_metrics_from_alpha(alpha_data))
                    result["checks_passed"] = self._infer_checks_passed_from_alpha(alpha_data)
                except Exception as exc:
                    result["alpha_fetch_error"] = str(exc)
                    result.update(
                        {
                            "sharpe": None,
                            "fitness": None,
                            "turnover": None,
                            "returns": None,
                            "margin": None,
                            "drawdown": None,
                            "checks_passed": False,
                        }
                    )
            else:
                result.update(
                    {
                        "sharpe": None,
                        "fitness": None,
                        "turnover": None,
                        "returns": None,
                        "margin": None,
                        "drawdown": None,
                        "checks_passed": True,
                    }
                )

        elif status in {"failed", "fail", "error"}:
            result["status"] = "failed"
            result["error_message"] = self._extract_error(raw)

        return result

    def submit_alpha(self, alpha_id: str, sim_id: str | None = None) -> dict[str, Any]:
        """
        Submit an alpha for out-of-sample testing.

        Flow:
          1. POST /alphas/{id}/submit -> 201 empty body, Retry-After header
          2. poll GET /alphas/{id}/submit:
               200 empty body = still processing
               200 with JSON   = passed (alpha enters OS)
               403 with JSON   = failed (self-correlation or another check)
          3. on failure the alpha reverts to unsubmitted (no daily-cap cost)

        Returns _accepted (True/False/None), _checks, _self_correlation,
        _correlated_with and _fail_reason.
        """
        self.ensure_session()

        submit_url = f"{self.base_url}/alphas/{alpha_id}/submit"

        # step 1: POST to initiate submission
        response = self.session.post(submit_url, timeout=60)

        if response.status_code == 401:
            self.login()
            response = self.session.post(submit_url, timeout=60)

        if response.status_code not in (200, 201, 202):
            # immediate rejection (alpha not eligible, daily cap hit, etc.)
            error_body = response.text[:500]
            print(
                f"[SUBMIT_REJECTED] alpha_id={alpha_id} "
                f"status={response.status_code} body={error_body}"
            )
            return {
                "_accepted": False,
                "_checks": [],
                "_self_correlation": None,
                "_correlated_with": None,
                "_fail_reason": f"POST rejected: {response.status_code} {error_body}",
            }

        retry_after = float(response.headers.get("Retry-After", 1.0))
        print(
            f"[SUBMIT_POSTED] alpha_id={alpha_id} "
            f"status={response.status_code} retry_after={retry_after}"
        )

        # step 2: poll for check results
        max_polls = 30
        poll_interval = max(retry_after, 1.0)

        for poll_num in range(1, max_polls + 1):
            time.sleep(poll_interval)

            resp = self.session.get(submit_url, timeout=30)

            # 200 empty = still processing
            if resp.status_code == 200 and len(resp.text.strip()) == 0:
                continue

            # 200 with JSON = passed, 403 with JSON = failed
            if resp.status_code in (200, 403) and len(resp.text.strip()) > 0:
                try:
                    data = resp.json()
                except ValueError:
                    continue

                checks = data.get("is", {}).get("checks", [])
                if not checks:
                    continue  # not the final response yet

                failed_checks = []
                all_checks = []
                self_corr_value = None
                correlated_with = None

                for check in checks:
                    name = check.get("name", "?")
                    result = check.get("result", "?")
                    value = check.get("value")
                    limit = check.get("limit")

                    all_checks.append(check)

                    if result == "PENDING":
                        break  # not finished yet

                    if result == "FAIL":
                        failed_checks.append(check)
                        if name == "SELF_CORRELATION" and value is not None:
                            self_corr_value = float(value)

                    # don't override WQ's SELF_CORRELATION verdict. its PASS already
                    # accounts for the sharpe-outperformance override (an alpha whose
                    # sharpe beats its closest correlate is allowed past the 0.7 raw
                    # limit). second-guessing it just created false negatives that
                    # aborted valid submissions - so only record the value for logging.
                    if name == "SELF_CORRELATION" and value is not None:
                        try:
                            self_corr_value = float(value)
                        except (TypeError, ValueError):
                            pass

                    status_icon = "+" if result == "PASS" else "-" if result == "FAIL" else "~"
                    print(
                        f"[SUBMIT_CHECK] {status_icon} {name}: {result} "
                        f"(value={value}, limit={limit})"
                    )
                else:
                    # all checks resolved (no PENDING break)
                    self_correlated = data.get("is", {}).get("selfCorrelated", {})
                    records = self_correlated.get("records", [])
                    if records and len(records) > 0 and len(records[0]) > 0:
                        correlated_with = records[0][0]  # first element is the alpha_id
                        if self_corr_value is None and len(records[0]) > 5:
                            self_corr_value = records[0][5]  # correlation value

                    if failed_checks:
                        fail_names = [c["name"] for c in failed_checks]
                        print(
                            f"[SUBMIT_FAILED] alpha_id={alpha_id} "
                            f"failed_checks={fail_names} "
                            f"self_correlation={self_corr_value} "
                            f"correlated_with={correlated_with}"
                        )
                        return {
                            "_accepted": False,
                            "_checks": all_checks,
                            "_self_correlation": self_corr_value,
                            "_correlated_with": correlated_with,
                            "_fail_reason": f"checks_failed:{','.join(fail_names)}",
                        }
                    else:
                        print(
                            f"[SUBMIT_ACCEPTED] alpha_id={alpha_id} "
                            f"all {len(all_checks)} checks PASSED "
                            f"self_correlation={self_corr_value}"
                        )
                        return {
                            "_accepted": True,
                            "_checks": all_checks,
                            "_self_correlation": self_corr_value,
                            "_correlated_with": None,
                            "_fail_reason": None,
                        }

                    continue  # had a PENDING - keep polling

            # unexpected status
            if resp.status_code not in (200, 403):
                print(
                    f"[SUBMIT_POLL_UNEXPECTED] poll={poll_num} "
                    f"status={resp.status_code} body={resp.text[:200]}"
                )

        # timed out polling
        print(f"[SUBMIT_TIMEOUT] alpha_id={alpha_id} timed out after {max_polls} polls")
        return {
            "_accepted": None,
            "_checks": [],
            "_self_correlation": None,
            "_correlated_with": None,
            "_fail_reason": "polling_timeout",
        }

    def check_alpha(self, alpha_id: str) -> dict[str, Any]:
        """
        Check self-correlation without submitting. Uses GET /alphas/{id}/check,
        same response format as submit but the alpha is not committed.

        Returns _passed (True/False/None), _checks, _self_correlation,
        _correlated_with and _fail_reason.
        """
        self.ensure_session()

        check_url = f"{self.base_url}/alphas/{alpha_id}/check"

        # step 1: GET to initiate check
        response = self.session.get(check_url, timeout=60)

        if response.status_code == 401:
            self.login()
            response = self.session.get(check_url, timeout=60)

        if response.status_code not in (200, 201, 202):
            error_body = response.text[:500]
            return {
                "_passed": None,
                "_checks": [],
                "_self_correlation": None,
                "_correlated_with": None,
                "_fail_reason": f"check initiation failed: {response.status_code} {error_body}",
            }

        retry_after = float(response.headers.get("Retry-After", 1.0))

        # step 2: poll for check results
        max_polls = 150
        poll_interval = max(retry_after, 2.0)

        for poll_num in range(1, max_polls + 1):
            time.sleep(poll_interval)

            resp = self.session.get(check_url, timeout=30)

            # 200 empty = still processing
            if resp.status_code == 200 and len(resp.text.strip()) == 0:
                continue

            # 200 with JSON = passed, 403 with JSON = failed
            if resp.status_code in (200, 403) and len(resp.text.strip()) > 0:
                try:
                    data = resp.json()
                except ValueError:
                    continue

                checks = data.get("is", {}).get("checks", [])
                if not checks:
                    continue

                failed_checks = []
                all_checks = []
                self_corr_value = None
                correlated_with = None

                for check in checks:
                    name = check.get("name", "?")
                    result = check.get("result", "?")
                    value = check.get("value")
                    limit = check.get("limit")

                    all_checks.append(check)

                    if result == "PENDING":
                        break

                    if result == "FAIL":
                        failed_checks.append(check)
                        if name == "SELF_CORRELATION" and value is not None:
                            self_corr_value = float(value)

                    # as in submit_alpha: record the corr value but don't override
                    # WQ's PASS decision, which already handles the sharpe override.
                    if name == "SELF_CORRELATION" and value is not None:
                        try:
                            self_corr_value = float(value)
                        except (TypeError, ValueError):
                            pass
                else:
                    # all checks complete - print results
                    for check in checks:
                        name = check.get("name", "?")
                        result = check.get("result", "?")
                        value = check.get("value")
                        limit = check.get("limit")
                        status_icon = "+" if result == "PASS" else "-" if result == "FAIL" else "~"
                        print(
                            f"[CHECK] {status_icon} {name}: {result} "
                            f"(value={value}, limit={limit})"
                        )
                    self_correlated = data.get("is", {}).get("selfCorrelated", {})
                    records = self_correlated.get("records", [])
                    if records and len(records) > 0 and len(records[0]) > 0:
                        correlated_with = records[0][0]
                        if self_corr_value is None and len(records[0]) > 5:
                            self_corr_value = records[0][5]

                    passed = len(failed_checks) == 0
                    return {
                        "_passed": passed,
                        "_checks": all_checks,
                        "_self_correlation": self_corr_value,
                        "_correlated_with": correlated_with,
                        "_fail_reason": f"checks_failed:{','.join(c['name'] for c in failed_checks)}" if failed_checks else None,
                    }

                continue

        return {
            "_passed": None,
            "_checks": [],
            "_self_correlation": None,
            "_correlated_with": None,
            "_fail_reason": "polling_timeout",
        }

    def check_before_after_performance(self, alpha_id: str, competition_id: str = "IQC2026S1") -> dict[str, Any]:
        """
        Check merged performance impact without submitting, via
        GET /competitions/{comp_id}/alphas/{alpha_id}/before-and-after-performance.

        Returns before/after score, the change, before/after sharpe, fitness
        and pnl, plus _raw and _error.
        """
        self.ensure_session()

        url = f"{self.base_url}/competitions/{competition_id}/alphas/{alpha_id}/before-and-after-performance"

        response = self.session.get(url, timeout=60)

        if response.status_code == 401:
            self.login()
            response = self.session.get(url, timeout=60)

        if response.status_code not in (200, 201, 202):
            return {
                "_score_before": None,
                "_score_after": None,
                "_score_change": None,
                "_before_sharpe": None,
                "_after_sharpe": None,
                "_before_fitness": None,
                "_after_fitness": None,
                "_before_pnl": None,
                "_after_pnl": None,
                "_raw": None,
                "_error": f"request failed: {response.status_code} {response.text[:200]}",
            }

        retry_after = float(response.headers.get("Retry-After", 1.0))

        # poll for results
        max_polls = 30
        poll_interval = max(retry_after, 1.5)

        for poll_num in range(1, max_polls + 1):
            time.sleep(poll_interval)

            resp = self.session.get(url, timeout=30)

            if resp.status_code == 200 and len(resp.text.strip()) == 0:
                continue

            if resp.status_code == 200 and len(resp.text.strip()) > 0:
                try:
                    data = resp.json()
                except ValueError:
                    continue

                # response carries stats (portfolio metrics) and score (IQC points)
                stats = data.get("stats", {})
                before_stats = stats.get("before", {})
                after_stats = stats.get("after", {})

                score = data.get("score", {})
                score_before = score.get("before")
                score_after = score.get("after")

                if score_before is None and not before_stats:
                    continue  # not the final response yet

                score_change = None
                if score_before is not None and score_after is not None:
                    score_change = round(score_after - score_before, 1)

                return {
                    "_score_before": score_before,
                    "_score_after": score_after,
                    "_score_change": score_change,
                    "_before_sharpe": before_stats.get("sharpe"),
                    "_after_sharpe": after_stats.get("sharpe"),
                    "_before_fitness": before_stats.get("fitness"),
                    "_after_fitness": after_stats.get("fitness"),
                    "_before_pnl": before_stats.get("pnl"),
                    "_after_pnl": after_stats.get("pnl"),
                    "_raw": data,
                    "_error": None,
                }

        return {
            "_score_before": None,
            "_score_after": None,
            "_score_change": None,
            "_before_sharpe": None,
            "_after_sharpe": None,
            "_before_fitness": None,
            "_after_fitness": None,
            "_before_pnl": None,
            "_after_pnl": None,
            "_raw": None,
            "_error": "polling_timeout",
        }

    def wait_for_completion(
        self,
        sim_id: str,
        poll_interval_seconds: int = 10,
        timeout_minutes: int = 45,
    ) -> dict[str, Any]:
        """
        Debug helper only - blocks, so the production bot should not use it.
        """
        deadline = time.time() + timeout_minutes * 60

        while time.time() < deadline:
            result = self.poll_simulation(sim_id)
            if result["status"] in {"completed", "failed", "timed_out"}:
                return result
            time.sleep(poll_interval_seconds)

        return {
            "status": "timed_out",
            "raw": {},
            "error_message": f"Polling exceeded {timeout_minutes} minutes.",
        }

    def _build_simulation_payload(
        self,
        expression: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Build the BRAIN simulation payload. Internal settings are snake_case;
        the API expects camelCase with a specific set of required keys.
        """
        api_settings = {
            "instrumentType": config.DEFAULT_INSTRUMENT_TYPE,
            "region": settings["region"],
            "universe": settings["universe"],
            "delay": settings["delay"],
            "decay": settings["decay"],
            "neutralization": settings["neutralization"],
            "truncation": settings["truncation"],
            "pasteurization": settings["pasteurization"],
            "unitHandling": settings["unit_handling"],
            "nanHandling": settings["nan_handling"],
            "language": settings["language"],
            "visualization": config.DEFAULT_VISUALIZATION,
        }

        return {
            "type": "REGULAR",
            "settings": api_settings,
            "regular": expression,
        }

    def _simulation_status_url(self, sim_id: str) -> str:
        """
        If submit returned a full URL, use it directly; otherwise treat sim_id
        as an id under /simulations/{id}.
        """
        if sim_id.startswith("http://") or sim_id.startswith("https://"):
            return sim_id
        return f"{self.base_url}{self.simulation_path}/{sim_id}"

    def _extract_simulation_id(self, response: requests.Response) -> Optional[str]:
        """
        Try the common return patterns: a Location header, or id /
        simulation_id / progress_id in the JSON body.
        """
        location = response.headers.get("Location")
        if location:
            return location

        raw = self._parse_json(response)

        for key in ("id", "simulation_id", "progress_id"):
            if key in raw and raw[key]:
                return str(raw[key])

        return None

    def _extract_status(self, raw: dict[str, Any]) -> str:
        """
        Normalise platform statuses to:
        submitted / running / completed / failed / timed_out.
        """
        candidates = [
            raw.get("status"),
            raw.get("state"),
            raw.get("simulation", {}).get("status")
            if isinstance(raw.get("simulation"), dict)
            else None,
        ]

        status = None
        for item in candidates:
            if item:
                status = str(item).lower()
                break

        if status is None:
            return "running"

        if status in {"queued", "submitted", "pending"}:
            return "submitted"
        if status in {"running", "processing", "in_progress"}:
            return "running"
        if status in {"completed", "complete", "done", "success"}:
            return "completed"
        if status in {"warning"}:
            return "completed"  # treat warnings as completed runs
        if status in {"failed", "error"}:
            return "failed"
        if status in {"timed_out", "timeout"}:
            return "timed_out"

        return status

    def _extract_metrics(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        Pull likely metrics out of the response payload.
        """
        source = raw
        if isinstance(raw.get("result"), dict):
            source = raw["result"]

        return {
            "sharpe": self._get_nested_value(source, ["sharpe"]),
            "fitness": self._get_nested_value(source, ["fitness"]),
            "turnover": self._get_nested_value(source, ["turnover"]),
            "returns": self._get_nested_value(source, ["returns"]),
            "margin": self._get_nested_value(source, ["margin"]),
            "drawdown": self._get_nested_value(source, ["drawdown"]),
            "checks_passed": self._infer_checks_passed(raw),
        }

    def _infer_checks_passed(self, raw: dict[str, Any]) -> bool:
        checks = raw.get("checks")
        if isinstance(checks, list):
            dict_checks = [item for item in checks if isinstance(item, dict)]
            if dict_checks:
                return all(bool(item.get("passed", False)) for item in dict_checks)

        if isinstance(raw.get("is"), dict):
            maybe = raw["is"].get("stats_pass")
            if maybe is not None:
                return bool(maybe)

        return True

    def _extract_error(self, raw: dict[str, Any]) -> str:
        for key in ("error", "message", "detail"):
            if key in raw and raw[key]:
                return str(raw[key])
        return "Unknown simulation error"

    def get_alpha(self, alpha_id: str) -> dict[str, Any]:
        """
        Fetch alpha details after a simulation completes - this is where the
        performance stats live.
        """
        self.ensure_session()

        url = f"{self.base_url}/alphas/{alpha_id}"
        response = self.session.get(url, timeout=self.timeout_seconds)

        if response.status_code == 401:
            self.login()
            response = self.session.get(url, timeout=self.timeout_seconds)

        if response.status_code != 200:
            raise BrainAPIError(
                f"Fetching alpha failed with status {response.status_code}: {response.text}"
            )

        alpha_data = self._parse_json(response)
        return alpha_data

    def _extract_metrics_from_alpha(self, alpha_data: dict[str, Any]) -> dict[str, Any]:
        """
        Extract metrics from the alpha-details payload. Several likely locations
        are tried because the response shape varies.
        """
        candidates = [
            alpha_data,
            alpha_data.get("is") if isinstance(alpha_data.get("is"), dict) else None,
            alpha_data.get("inSample") if isinstance(alpha_data.get("inSample"), dict) else None,
            alpha_data.get("in_sample") if isinstance(alpha_data.get("in_sample"), dict) else None,
            alpha_data.get("metrics") if isinstance(alpha_data.get("metrics"), dict) else None,
        ]

        source = {}
        for candidate in candidates:
            if isinstance(candidate, dict):
                source.update(candidate)

        return {
            "sharpe": self._coalesce_metric(source, ["sharpe", "sharpeRatio"]),
            "fitness": self._coalesce_metric(source, ["fitness"]),
            "turnover": self._coalesce_metric(source, ["turnover"]),
            "returns": self._coalesce_metric(source, ["returns", "return"]),
            "margin": self._coalesce_metric(source, ["margin"]),
            "drawdown": self._coalesce_metric(source, ["drawdown", "maxDrawdown"]),
        }

    def _infer_checks_passed_from_alpha(self, alpha_data: dict[str, Any]) -> bool:
        is_block = alpha_data.get("is")
        if not isinstance(is_block, dict):
            return True

        checks = is_block.get("checks")
        if not isinstance(checks, list):
            return True

        for check in checks:
            if not isinstance(check, dict):
                continue

            name = str(check.get("name", "")).upper()
            result = str(check.get("result", "")).upper()

            if result == "FAIL":
                return False

            # allow pending self-correlation to continue for now
            if result == "PENDING" and name != "SELF_CORRELATION":
                return False

        return True

    @staticmethod
    def _coalesce_metric(source: dict[str, Any], keys: list[str]) -> Any:
        for key in keys:
            if key in source and source[key] is not None:
                return source[key]
        return None

    @staticmethod
    def _parse_json(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
            if isinstance(data, dict):
                return data
            return {"data": data}
        except ValueError:
            return {"text": response.text}

    @staticmethod
    def _get_nested_value(source: dict[str, Any], path: list[str]) -> Any:
        cur: Any = source
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        return cur
