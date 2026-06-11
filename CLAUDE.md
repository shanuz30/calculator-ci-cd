# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository has two independent codebases that coexist without a shared build system:

1. **Calculator module + pytest tests** — `test_calculator_pytest.py` imports from a `calculator` module (`add`, `subtract`, `multiply`, `divide`). The `calculator.py` file does **not exist yet** and must be created before tests can pass.
2. **Oxocard MQTT sensor script** — `mqtt_sensor_monitor.py` runs on Oxocard hardware; it connects to HiveMQ Cloud and publishes CO2/NOx/temperature readings. It depends on Oxocard-specific built-ins (`getCO2()`, `getNOx()`, `getTemperature()`, `connectMQTT()`, etc.) that are only available on the device — this file cannot be run on a standard Python interpreter.

## Commands

```bash
# Run all tests
pytest test_calculator_pytest.py

# Run a single test function
pytest test_calculator_pytest.py::test_add

# Run with verbose output
pytest test_calculator_pytest.py -v
```

No dependency installation step is needed — the only external dependency is `pytest`, which should already be available.

## Calculator Module Contract

The test file defines the expected interface for `calculator.py`:

| Function | Behavior |
|---|---|
| `add(a, b)` | Returns `a + b` |
| `subtract(a, b)` | Returns `a - b` |
| `multiply(a, b)` | Returns `a * b` |
| `divide(a, b)` | Returns `a / b`; raises `ValueError` when `b == 0` |

## Security

MQTT broker credentials were previously committed in plain text and are visible in git history (commit `043cb8c`). The current `mqtt_sensor_monitor.py` uses placeholder strings. **Never commit real credentials** — fill them in locally on the Oxocard device only.

## MCP Configuration

`.mcp.json` configures the Sequential Thinking MCP server (`@modelcontextprotocol/server-sequential-thinking`), available via `npx`. The `.claude/` directory also contains a `desperation-vector` skill for multi-vector research when standard search approaches fail.
