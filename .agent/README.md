# Agent Instructions

This directory contains agent instructions from installed packages.
Agents can read these files for context about how to use the packages.

## Installed Packages

| Namespace | Ecosystem | Package | Entry File |
|-----------|-----------|---------|------------|
| `ansys.dyna.core` | pypi | ansys-dyna-core | [ansys.dyna.core.md](ansys.dyna.core.md) |

## Usage

Each package provides its own installation command. For Python packages with
agent instructions, you can typically run:

```bash
python -m <package> agent --copy
```

## Scanning Dependencies

To install agent instructions from all packages in your requirements:

```bash
# Future: python -m agent_instructions scan requirements.txt
# For now, run each package's agent command individually
```

---
*Auto-generated manifest. Regenerate by running package agent commands.*
