from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

JAVA_LANGUAGE = Language(tsjava.language())
parser = Parser(JAVA_LANGUAGE)

@dataclass
class SlicedMethod:
    file_path: Path
    method_name: str
    start_line: int  # 1-indexed
    end_line: int    # 1-indexed
    source_code: str

def find_java_file(project_root: str, class_name: str) -> Optional[Path]:
    rel_path = Path(*class_name.split(".")).with_suffix(".java")
    candidate = Path(project_root) / "src" / "main" / "java" / rel_path
    return candidate if candidate.exists() else None

def extract_method_at_line(java_file: Path, target_line: int) -> Optional[SlicedMethod]:
    source_bytes = java_file.read_bytes()
    tree = parser.parse(source_bytes)
    lines = source_bytes.decode("utf-8").splitlines()

    def walk(node):
        if node.type == "method_declaration":
            # tree-sitter rows are 0-indexed; stack traces are 1-indexed
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            if start_line <= target_line <= end_line:
                name_node = node.child_by_field_name("name")
                method_name = name_node.text.decode("utf-8") if name_node else "unknown"
                snippet = "\n".join(lines[start_line - 1 : end_line])
                return SlicedMethod(
                    file_path=java_file,
                    method_name=method_name,
                    start_line=start_line,
                    end_line=end_line,
                    source_code=snippet
                )
        for child in node.children:
            result = walk(child)
            if result:
                return result
        return None

    return walk(tree.root_node)

if __name__ == "__main__":
    from log_parser import parse_latest_defects

    project_dir = r"C:\Users\htota\mcp\springboot-calculator-seed"
    log_file = rf"{project_dir}\logs\app.log"

    for defect in parse_latest_defects(log_file):
        java_path = find_java_file(project_dir, defect.class_name)
        if java_path:
            sliced = extract_method_at_line(java_path, defect.line_number)
            if sliced:
                print(f"\n--- Sliced {sliced.method_name}() [{sliced.start_line}-{sliced.end_line}] ---")
                print(sliced.source_code)
