import shutil
import subprocess
from pathlib import Path
from log_parser import parse_latest_defects
from java_slicer import find_java_file, extract_method_at_line
from jetson_agent import generate_reproduction_test, generate_method_fix

PROJECT_DIR = Path(r"C:\Users\htota\mcp\springboot-calculator-seed")
LOG_FILE = PROJECT_DIR / "logs" / "app.log"

def run_mvn_test() -> tuple[bool, str]:
    mvnw = str(PROJECT_DIR / "mvnw.cmd")
    result = subprocess.run(
        [mvnw, "test"],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True
    )
    passed = result.returncode == 0
    return passed, result.stdout + "\n" + result.stderr

def extract_mvn_errors(mvn_output: str) -> str:
    error_lines = [
        line for line in mvn_output.splitlines()
        if "[ERROR]" in line or "AssertionFailedError" in line or "Exception" in line
    ]
    return "\n".join(error_lines[:20]) if error_lines else mvn_output[-1000:]

def apply_method_patch(java_file: Path, start_line: int, end_line: int, new_method_code: str):
    lines = java_file.read_text(encoding="utf-8").splitlines()
    indent = "    "
    indented_new = [
        (indent + line if line.strip() and not line.startswith("    ") else line)
        for line in new_method_code.splitlines()
    ]
    updated = lines[: start_line - 1] + indented_new + lines[end_line:]
    java_file.write_text("\n".join(updated) + "\n", encoding="utf-8")

def process_defects():
    defects = parse_latest_defects(str(LOG_FILE))
    if not defects:
        print("No application defects found in logs.")
        return

    for defect in defects:
        print(f"\n==========================================")
        print(f"[DEFECT] {defect.exception_type} in {defect.class_name}.{defect.method_name}() (Line {defect.line_number})")

        java_file = find_java_file(str(PROJECT_DIR), defect.class_name)
        if not java_file:
            print(f"[SKIP] Source file not found for {defect.class_name}")
            continue

        sliced = extract_method_at_line(java_file, defect.line_number)
        if not sliced:
            print(f"[SKIP] Could not slice method at line {defect.line_number}")
            continue

        # 1. Generate JUnit 5 reproduction test on Jetson
        print("[1/4] Asking Jetson (qwen2.5-coder:3b) to generate JUnit 5 reproduction test...")
        test_code = generate_reproduction_test(defect, sliced)

        rel_pkg_dir = Path(*defect.class_name.split(".")[:-1])
        simple_class = defect.class_name.split(".")[-1]
        test_file = PROJECT_DIR / "src" / "test" / "java" / rel_pkg_dir / f"{simple_class}_{defect.method_name}AutoTest.java"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(test_code, encoding="utf-8")

        # 2. Verify test fails against unpatched code
        print("[2/4] Running mvnw test to verify bug reproduction...")
        passed_before, output_before = run_mvn_test()
        if passed_before:
            print("[WARN] Generated test passed without a fix (did not reproduce bug). Cleaning up test.")
            test_file.unlink(missing_ok=True)
            continue
        if "COMPILATION ERROR" in output_before:
            print("[WARN] Generated test had a compilation error:\n" + extract_mvn_errors(output_before))
            test_file.unlink(missing_ok=True)
            continue
        print("[OK] Bug reproduced! Test failed as expected.")

        # 3 & 4. Generate fix on Jetson and verify with up to 2 retries
        backup_file = java_file.with_suffix(".java.bak")
        shutil.copy2(java_file, backup_file)

        previous_error = ""
        fixed = False
        for attempt in range(1, 3):
            print(f"[3/4] Asking Jetson (qwen2.5-coder:3b) to generate method fix (Attempt {attempt}/2)...")
            fixed_method = generate_method_fix(defect, sliced, test_code, previous_error)

            shutil.copy2(backup_file, java_file)
            apply_method_patch(java_file, sliced.start_line, sliced.end_line, fixed_method)

            print(f"[4/4] Running mvnw test to verify patched method (Attempt {attempt}/2)...")
            passed_after, output_after = run_mvn_test()
            if passed_after:
                print(f"[SUCCESS] Fix verified! {java_file.name} patched and {test_file.name} passes.")
                backup_file.unlink(missing_ok=True)
                fixed = True
                break
            else:
                previous_error = extract_mvn_errors(output_after)
                print(f"[RETRY] Attempt {attempt} failed:\n{previous_error}")

        if fixed:
            break  # Stop after one verified fix so line numbers remain accurate for the next run
        else:
            print("[ROLLBACK] All patch attempts failed. Restoring original file.")
            shutil.copy2(backup_file, java_file)
            backup_file.unlink(missing_ok=True)
            test_file.unlink(missing_ok=True)

if __name__ == "__main__":
    process_defects()
