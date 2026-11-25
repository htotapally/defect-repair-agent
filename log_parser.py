import re
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

APP_PACKAGE_PREFIX = "com.aiops.governance.calculator"

@dataclass
class StackFrameDefect:
    exception_type: str
    message: str
    class_name: str
    method_name: str
    file_name: str
    line_number: int
    raw_trace: str

def parse_latest_defects(log_path: str) -> List[StackFrameDefect]:
    text = Path(log_path).read_text(encoding="utf-8", errors="ignore")
    
    # Match Java exception header followed by stack frames
    exception_pattern = re.compile(
        r"((?:java|jakarta|org|com)\.[\w.$]+(?:Exception|Error)):\s*(.*?)\r?\n((?:\s+at\s+.*\r?\n)+)"
    )
    frame_pattern = re.compile(
        rf"\s+at\s+({re.escape(APP_PACKAGE_PREFIX)}\.[\w.$]+)\.([\w$<>]+)\(([\w]+\.java):(\d+)\)"
    )

    defects = []
    seen_signatures = set()

    for match in exception_pattern.finditer(text):
        exc_type, exc_msg, stack_block = match.groups()
        app_frame = frame_pattern.search(stack_block)
        if not app_frame:
            continue

        class_name, method_name, file_name, line_str = app_frame.groups()
        line_num = int(line_str)
        signature = f"{exc_type}:{file_name}:{line_num}"

        if signature not in seen_signatures:
            seen_signatures.add(signature)
            defects.append(StackFrameDefect(
                exception_type=exc_type,
                message=exc_msg.strip(),
                class_name=class_name,
                method_name=method_name,
                file_name=file_name,
                line_number=line_num,
                raw_trace=f"{exc_type}: {exc_msg}\n{stack_block.strip()}"
            ))

    return defects

if __name__ == "__main__":
    # Point this to your Spring Boot app.log
    log_file = r"C:\Users\htota\mcp\springboot-calculator-seed\logs\app.log"
    found = parse_latest_defects(log_file)
    for d in found:
        print(f"[FOUND] {d.exception_type} at {d.file_name}:{d.line_number} in {d.method_name}() -> {d.message}")
