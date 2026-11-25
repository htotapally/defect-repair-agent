# Defect Repair Agent

An autonomous, test-driven Java defect-repair pipeline that reads production stack traces, slices failing atomic methods via `tree-sitter-java`, generates JUnit 5 reproduction tests and patches on an **8GB NVIDIA Jetson Orin Nano (`qwen2.5-coder:3b`)**, and verifies fixes locally via Maven.

Designed to target **[springboot-calculator-seed](https://github.com)** (and extendable to any atomic Java/Spring Boot service).

## Split-Node Architecture

To avoid Out-Of-Memory (OOM) contention on an 8GB edge GPU while running heavy JVM builds, the workload is split across two nodes over LAN:

```text
┌──────────────────────────────────────────────┐    LAN (HTTP)    ┌────────────────────────────────┐
│          Workstation Control Plane           │ ───────────────► │   NVIDIA Jetson Orin Nano      │
│           (defect-repair-agent)              │                  │   (8GB Unified RAM - Headless) │
│                                              │                  │                                │
│  1. log_parser.py   -> Extract stack frame   │                  │  • Ubuntu multi-user.target    │
│  2. java_slicer.py  -> Slice atomic method   │                  │  • Ollama API (:11434)         │
│  3. jetson_agent.py -> Enforce guardrails    │ ◄─────────────── │  • qwen2.5-coder:3b            │
│  4. verifier.py     -> Run mvnw.cmd test     │  Test & Patch    │    (num_ctx: 4096)             │
└──────────────────────────────────────────────┘                  └────────────────────────────────┘
```

## Repository Components

| File | Role |
| :--- | :--- |
| `log_parser.py` | Parses Spring Boot `logs/app.log`, deduplicates exceptions, and extracts the exception type, message, Java class, method name, and exact crashing line number. |
| `java_slicer.py` | Uses `tree-sitter-java` to extract **only** the atomic method surrounding the crashing line number, keeping LLM context compact and focused. |
| `jetson_agent.py` | Communicates with Ollama on the Jetson (`qwen2.5-coder:3b`) and applies deterministic Python guardrails (JUnit 5 import injection, exception-contract alignment, and stack-trace anchoring). |
| `verifier.py` | Orchestrates the 4-gate closed-loop verification: generates a JUnit 5 test, confirms it fails on unpatched code, applies the method patch (with `.bak` backup), runs `mvnw.cmd test` with self-correction retries, and rolls back automatically on failure. |

## Setup & Installation

### 1. Edge Inference Node (NVIDIA Jetson Orin Nano 8GB)
Switch the Jetson to headless mode to free ~700 MB of unified RAM, pull `qwen2.5-coder:3b`, and expose Ollama on your LAN:

```bash
ollama pull qwen2.5-coder:3b
sudo systemctl edit ollama.service
# Add under [Service]:
# Environment="OLLAMA_HOST=0.0.0.0:11434"

sudo systemctl daemon-reload
sudo systemctl restart ollama
sudo systemctl set-default multi-user.target
sudo reboot
```

### 2. Workstation Control Plane (Windows / Linux)
```powershell
git clone https://github.com
cd defect-repair-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install tree-sitter tree-sitter-java requests
```

Update `OLLAMA_URL` in `jetson_agent.py` with your Jetson's LAN IP and `PROJECT_DIR` in `verifier.py` with the local path to your Spring Boot target repository.

## Usage

Ensure `JAVA_HOME` points to your local JDK/JRE (JDK 17/21), then run the repair loop:

```powershell
.\.venv\Scripts\python.exe verifier.py
```

### Sample Verification Output
```text
==========================================
[DEFECT] java.lang.ArithmeticException in com.aiops.governance.calculator.service.CalculatorService.divide() (Line 31)
[1/4] Asking Jetson (qwen2.5-coder:3b) to generate JUnit 5 reproduction test...
[2/4] Running mvnw test to verify bug reproduction...
[OK] Bug reproduced! Test failed as expected.
[3/4] Asking Jetson (qwen2.5-coder:3b) to generate method fix (Attempt 1/2)...
[4/4] Running mvnw test to verify patched method (Attempt 1/2)...
[SUCCESS] Fix verified! CalculatorService.java patched and CalculatorService_divideAutoTest.java passes.
```

## Roadmap
* [x] Log parsing & `tree-sitter-java` atomic method slicing
* [x] Dynamic JUnit 5 test synthesis from zero existing tests
* [x] Closed-loop `mvnw.cmd test` verification with automatic `.bak` rollback
* [ ] Real-time file tailing (`log_watcher.py`) with exception fingerprinting
* [ ] Automated Git branch creation and Draft Pull Request generation
* [ ] Automatic fallback to `qwen2.5-coder:7b` for multi-step service logic
