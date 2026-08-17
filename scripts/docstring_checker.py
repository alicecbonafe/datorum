import importlib
import inspect
import sys
from typing import Any, Dict, List
import pydantic

# ANSI Color Codes for the terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def is_rest_docstring(doc: str | None) -> bool:
    """Check if a docstring is non-empty and follows reST formatting conventions."""
    if not doc or not doc.strip():
        return False

    rest_indicators = [":param", ":type", ":return:", ":rtype:", ":raises:", "::", "``"]
    lines = doc.strip().splitlines()

    if len(lines) == 1:
        return True

    return any(indicator in doc for indicator in rest_indicators) or any(
        line.strip().startswith("- ") or line.strip().startswith("* ") for line in lines
    )


def get_own_docstring(obj: Any) -> str | None:
    """Gets the docstring declared directly on the object, ignoring inheritance from the parent class."""
    raw_doc = None

    if inspect.isclass(obj):
        # Accesses the docstring directly from the class's own __dict__ to avoid inheritance.
        raw_doc = obj.__dict__.get("__doc__", None)
    elif inspect.isfunction(obj):
        raw_doc = getattr(obj, "__doc__", None)

    if raw_doc and isinstance(raw_doc, str):
        return inspect.cleandoc(raw_doc)

    return None


def check_package(package_name: str) -> None:
    try:
        pkg = importlib.import_module(package_name)
    except ImportError as e:
        print(f"{RED}Error importing package '{package_name}': {e}{RESET}")
        return

    exported_names = getattr(pkg, "__all__", None)
    if exported_names is None:
        print(f"{RED}Error: `{package_name}.__init__.py` does not define an `__all__` list.{RESET}")
        return

    inconsistencies: List[str] = []

    func_total = func_passed = 0
    class_total = class_passed = 0
    method_total = method_passed = 0
    field_total = field_passed = 0

    for name in exported_names:
        if name.startswith("_"):
            continue

        obj = getattr(pkg, name, None)
        if obj is None:
            inconsistencies.append(f"Member '{name}' listed in `__all__` was not found in module.")
            continue

        # 1. Top-level functions
        if inspect.isfunction(obj):
            func_total += 1
            doc = get_own_docstring(obj)
            if is_rest_docstring(doc):
                func_passed += 1
            else:
                inconsistencies.append(f"Function '{name}' lacks a valid reST docstring.")

        # 2. Top-level classes
        elif inspect.isclass(obj):
            class_total += 1
            doc = get_own_docstring(obj)
            if is_rest_docstring(doc):
                class_passed += 1
            else:
                inconsistencies.append(f"Class '{name}' lacks a valid reST docstring.")

            # Checks only methods declared directly within the class itself.
            for m_name, attr in obj.__dict__.items():
                # Ignore private members
                if m_name.startswith("_"):
                    continue
                if issubclass(obj, pydantic.BaseModel) and m_name == "model_post_init":
                    continue

                # Unwrap staticmethod/classmethod
                unwrapped = inspect.unwrap(attr) if hasattr(attr, "__func__") else attr

                if inspect.isroutine(unwrapped) or inspect.isfunction(unwrapped):
                    method_total += 1
                    m_doc = get_own_docstring(unwrapped)
                    if not m_doc:
                        inconsistencies.append(
                            f"Method '{obj.__name__}.{m_name}' lacks a docstring declaration."
                        )
                    elif is_rest_docstring(m_doc):
                        method_passed += 1
                    else:
                        inconsistencies.append(
                            f"Method '{obj.__name__}.{m_name}' lacks a valid reST docstring."
                        )

            # 3. Pydantic BaseModel fields
            if issubclass(obj, pydantic.BaseModel):
                fields: Dict[str, Any] = getattr(obj, "model_fields", getattr(obj, "model_fields", {}))
                for f_name, field_info in fields.items():
                    if f_name.startswith("_"):
                        continue

                    field_total += 1
                    description = getattr(field_info, "description", None)
                    if description and str(description).strip():
                        field_passed += 1
                    else:
                        inconsistencies.append(
                            f"Pydantic Field '{obj.__name__}.{f_name}' has an empty or missing description."
                        )

    # Display of the color-coded inconsistency report
    print("\n" + "=" * 60)
    print(f"{BOLD}{CYAN}DOCUMENTATION CHECK REPORT FOR PACKAGE: {package_name}{RESET}")
    print("=" * 60)
    if inconsistencies:
        for issue in inconsistencies:
            print(f" {RED}[!] {issue}{RESET}")
    else:
        print(f" {GREEN}[✓] All docs found!{RESET}")

    def format_pct(passed: int, total: int) -> str:
        if total == 0:
            return f"{YELLOW}N/A (0 checks){RESET}"
        pct = (passed / total) * 100
        color = GREEN if pct == 100 else (YELLOW if pct >= 80 else RED)
        return f"{color}{pct:.2f}% ({passed}/{total}){RESET}"

    total_passed = func_passed + class_passed + method_passed + field_passed
    total_checks = func_total + class_total + method_total + field_total

    # Display of percentages
    print("\n" + "-" * 60)
    print(f"{BOLD}DOCUMENTATION COMPLIANCE SUMMARY{RESET}")
    print("-" * 60)
    print(f"Functions (reST Docstrings): {format_pct(func_passed, func_total)}")
    print(f"Classes   (reST Docstrings): {format_pct(class_passed, class_total)}")
    print(f"Methods   (reST Docstrings): {format_pct(method_passed, method_total)}")
    print(f"Pydantic Field Descriptions: {format_pct(field_passed, field_total)}")
    print("-" * 60)
    print(f"{BOLD}Overall Package Compliance  : {format_pct(total_passed, total_checks)}{RESET}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else input("Enter package name to check: ")
    check_package(target)