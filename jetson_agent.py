import re
import requests
from log_parser import StackFrameDefect
from java_slicer import SlicedMethod

OLLAMA_URL = "http://192.168.1.171:11434/api/generate"
MODEL_NAME = "qwen2.5-coder:3b"

def _call_ollama(prompt: str) -> str:
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": 4096,
            "temperature": 0.1
        }
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    cleaned = re.sub(r"^```(?:java)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
    return cleaned

def generate_reproduction_test(defect: StackFrameDefect, sliced: SlicedMethod) -> str:
    simple_class = defect.class_name.split(".")[-1]
    package_name = ".".join(defect.class_name.split(".")[:-1])
    test_class_name = f"{simple_class}_{defect.method_name}AutoTest"

    if "NullPointerException" in defect.exception_type:
        trigger_instruction = f"Call `service.{sliced.method_name}(10, null)` and `service.{sliced.method_name}(null, 10)` to reproduce the `NullPointerException`."
    elif "ArithmeticException" in defect.exception_type:
        trigger_instruction = f"Call `service.{sliced.method_name}(10, 0)` to reproduce the `ArithmeticException`."
    else:
        trigger_instruction = f"Call `service.{sliced.method_name}(...)` with the exact invalid arguments shown in the stack trace ({defect.message})."

    prompt = f"""You are a senior Java developer writing a JUnit 5 reproduction test.
Write a complete, compilable JUnit 5 test class named `{test_class_name}` in package `{package_name}`.

Target Method:
```java
{sliced.source_code}
```

Production Crash Stack Trace:
{defect.raw_trace}

Requirements:
1. Instantiate `{simple_class} service = new {simple_class}();`.
2. {trigger_instruction}
3. Assert that the hardened method throws `IllegalArgumentException` using `assertThrows(IllegalArgumentException.class, () -> ...);` (which will FAIL against the current unpatched method and PASS once fixed).
4. Include ONE valid-input test method using evenly divisible integers (e.g., `assertEquals(5.0, service.divide(10, 2).doubleValue(), 0.0001);` for divide, or `assertEquals(15.0, service.add(10, 5).doubleValue(), 0.0001);` for add).
5. Do NOT test unrelated exceptions (do NOT test division by zero unless the method is `divide`).
6. Output ONLY valid Java code with proper imports (`org.junit.jupiter.api.Test`, `static org.junit.jupiter.api.Assertions.*`). No explanations.
"""
    raw_test = _call_ollama(prompt)
    short_exc = defect.exception_type.split(".")[-1]
    hardened_test = raw_test.replace(f"{short_exc}.class", "IllegalArgumentException.class")

    # Guarantee required JUnit 5 imports are present
    if "import org.junit.jupiter.api.Test;" not in hardened_test:
        hardened_test = hardened_test.replace(
            f"package {package_name};",
            f"package {package_name};\n\nimport org.junit.jupiter.api.Test;\nimport static org.junit.jupiter.api.Assertions.*;",
            1
        )
    return hardened_test





def generate_method_fix(
    defect: StackFrameDefect,
    sliced: SlicedMethod,
    failing_test_code: str,
    previous_error: str = ""
) -> str:
    retry_context = ""
    if previous_error:
        retry_context = f"""
Your previous patch failed `mvn test` with this error:
{previous_error}
Fix the compilation or assertion issue above.
"""

    prompt = f"""You are a senior Java developer fixing a runtime exception in an atomic method.
Rewrite ONLY the Java method `{sliced.method_name}` below so it validates inputs and throws `IllegalArgumentException` for invalid inputs (such as `null` parameters or division by zero), passing the JUnit 5 test.

Current Buggy Method:
```java
{sliced.source_code}
```

JUnit 5 Test to Pass:
```java
{failing_test_code}
```
{retry_context}
Rules:
- Output ONLY the complete replacement Java method (from `public Number {sliced.method_name}(...)` to its closing `}}`).
- Keep the exact same method signature (`public Number {sliced.method_name}(Number a, Number b)`).
- Do NOT output class declarations, package lines, imports, or explanations.
- Preserve the original return types (keep the `Integer` branch returning `int` and `Double` fallback returning `double`).
"""
    raw_fix = _call_ollama(prompt)
    short_exc = defect.exception_type.split(".")[-1]
    return raw_fix.replace(f"new {short_exc}(", "new IllegalArgumentException(")

