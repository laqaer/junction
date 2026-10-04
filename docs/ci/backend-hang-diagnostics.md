# Backend shard hang diagnostics (#104)

Status: diagnostic instrumentation for an intermittent worker-loss failure. Do not treat a green run as proof of a root-cause fix.

## Evidence and decision

Investigation base: `e799330a66a127ebfd1bff8277a91a9da9f1defc`.

Issue [#104](https://github.com/laqaer/junction/issues/104) records an intermittent Python 3.12 / shard 2 hang on PR #82 and on main run [37136986707](https://github.com/laqaer/junction/actions/runs/37136986707). Failed job [111248125629](https://github.com/laqaer/junction/actions/runs/37136986707/job/111248125629) lost worker `gw2` (`Not properly terminated`), continued to 99%, and was cancelled at the job limit without the normal pytest summary. The existing `--timeout=120` did not end that stall. The last printed test is not proof of the culprit in a concurrent run.

The same main run's later job [111459180984](https://github.com/laqaer/junction/actions/runs/37136986707/job/111459180984) passed shard 2 and coverage upload. This establishes intermittence, not resolution. Existing evidence does not distinguish an executing test, teardown, worker transport, session finalization, or interpreter shutdown. It does not establish shard imbalance. Do not rebalance shards or retry until green on this evidence.

## What is added

`scripts/ci_pytest_diagnostics.py` is an explicitly loaded, opt-in pytest plugin. Each controller/worker process records timestamped phase transitions, node IDs, PID, and worker ID to a line-buffered JSONL journal. It emits all-thread stacks every 60 seconds and keeps observing session finalization and interpreter shutdown. The controller relays stack files to the original stderr descriptor so pytest capture cannot hide the evidence until a summary that may never appear. Worker-loss callbacks emit the worker's last journal entries; crash-item callbacks name the node without modifying reports or rescheduling tests.

The plugin does not register signals, replace pytest-timeout timers, add retries, alter test outcomes, or configure workers, splitting, scheduling, or coverage. It does not intentionally record locals or environment values. Node IDs can still contain parameter values; use the repository's normal rules against secrets in test identifiers.

The first dedicated diagnostic run (37218162382) was invalid as reproduction evidence because the diagnostic recorder itself was affected by a test that patches `time.time`. The recorder raised `StopIteration` after `test/test_design_tweak_devproc.py::TestStartDevProc::test_detects_listening_port`, causing a worker internal error and a secondary xdist `KeyError`. That is a defect in the first diagnostic implementation, not evidence that this application test caused #104. The recorder is now failure-contained and has a regression probe for mocked clocks.

The validated instrumentation is loaded only in the ordinary Python 3.12 backend matrix in `.github/workflows/ci.yml`. The scheduler, shard count, `-n auto`, `--timeout=120`, coverage targets, strictness and test scope are unchanged. Each Python 3.12 shard uploads its diagnostic journal/stacks with `always()`; live console relay remains the fallback when cancellation prevents artifact upload. There is no retry-until-green path and no shard rebalancing change.

## Reproduction

From the repository root with the CI dependency set installed:

```bash
python -m pytest -p scripts.ci_pytest_diagnostics \
  --hang-diagnostics-dir="$(mktemp -d)" \
  -q -n auto --timeout=120 --splits 4 --group 2 \
  --cov=junction --cov=sage_lib
```

Keep the repository's existing pytest configuration, duration data, worker budget and strictness. Do not use a reduced suite, changed distribution, or repeated green run as evidence of resolution. Record the exact commit, Python version, run ID, job ID, attempt, outcome and coverage artifact for each reproduction.

To validate the diagnostic mechanism independently of application fixtures:

```bash
python -c 'import pytest, pytest_cov, pytest_timeout, xdist'
python -m unittest discover -s scripts -p test_ci_pytest_diagnostics.py -v
```

The import preflight makes missing xdist/timeout dependencies a CI failure rather than accepting skipped integration probes.

## Local evidence — October 4, 2026

On Python 3.13.5 / pytest 9.0.2, the isolated probes ran in 13.897 seconds: 10 passed; 2 skipped because this runtime lacked pytest-xdist and pytest-timeout. Passing probes cover opt-in inertness, phase journals, setup/call/teardown/session-finish stalls, interpreter thread-join stalls, console stacks visible before process exit, assertion and strict-XPASS failure preservation, and real coverage XML output.

The tested source bytes match GitHub at commit `5fa1d00b41ffd35c3288a0069cc87251ebc76097`:

| File | Git blob SHA |
| --- | --- |
| `scripts/ci_pytest_diagnostics.py` | `a74d85928ff81e6a149210b1ab75a8e7228d6c7e` |
| `scripts/test_ci_pytest_diagnostics.py` | `0f2a63769eae0c97eb76a93c80f867522ef15b68` |

These are diagnostic-mechanism tests, not a full backend shard reproduction. The runtime could not resolve direct GitHub downloads, so the repository and full Python 3.12 application environment were not available locally. The first remote diagnostic run exposed and failed on the instrumentation defect described above, so it is explicitly excluded as root-cause evidence. Subsequent exact-head normal-CI results are the acceptance evidence for the failure-contained instrumentation.

## Interpreting the next failure

Use the immediate `crashitem` line and worker journal for a lost worker. For a live stall, correlate the most recent phase/node ID with successive stack samples: setup/call/teardown identifies an active test; sessionfinish or interpreter-shutdown instead points to finalization. A worker-loss line without stack evidence is not enough to claim OOM or a particular exception. Preserve the first failing attempt and its artifacts before proposing a bounded reproduction/fix.

The daemon watchdog needs Python execution time; native code holding the GIL or runner termination can prevent new samples. Artifact upload is best effort at job cancellation. These limitations are not grounds to increase retries, suppress test failures, or lower coverage requirements.
