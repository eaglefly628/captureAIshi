# Code Style

## Python
- Python 3.11+, formatted with Black
- All paths use `pathlib.Path` internally
- Config files stored in `./configs/`, output in `./output/<session>/`

## Coordinates
- Pipeline uses Y-up right-handed (meters)
- Convert at driver boundary (e.g. UE5 is Z-up left-handed centimeters)

## Testing
```bash
python -m pytest tests/           # Unit tests
python main.py --dry-run --driver manual  # Verify path generation + CLI
```
