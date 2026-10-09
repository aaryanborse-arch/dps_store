CLASS_OPTIONS = ['Nursery', 'Pre-Prep', 'Prep'] + [str(i) for i in range(1, 11)] + [
    '11-math', '11-commerce', '11-bio', '11-humanities',
    '12-math', '12-commerce', '12-bio', '12-humanities',
]

CLASS_LABELS = {
    '11-math': 'XI - Math', '11-commerce': 'XI - Commerce',
    '11-bio': 'XI - Bio', '11-humanities': 'XI - Humanities',
    '12-math': 'XII - Math', '12-commerce': 'XII - Commerce',
    '12-bio': 'XII - Bio', '12-humanities': 'XII - Humanities',
}



def get_class_label(value):
    if value in CLASS_LABELS:
        return CLASS_LABELS[value]
    try:
        from app.pdf_utils import to_roman
        return to_roman(value)
    except Exception:
        return value

_ROMAN_TO_NUM = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10}


def normalize_class_value(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    lower = text.lower().strip().rstrip('.').strip()
    if lower.replace('.', '', 1).isdigit() and lower.endswith('.0'):
        lower = lower[:-2]  # Excel sometimes gives 3.0 instead of 3

    direct_map = {
        'nursery': 'Nursery', 'nur': 'Nursery', 'n': 'Nursery',
        'lkg': 'Pre-Prep', 'pre-prep': 'Pre-Prep', 'preprep': 'Pre-Prep',
        'ukg': 'Prep', 'prep': 'Prep',
    }
    if lower in direct_map:
        return direct_map[lower]

    if text in CLASS_OPTIONS:
        return text

    if lower in _ROMAN_TO_NUM:
        return str(_ROMAN_TO_NUM[lower])

    if lower.isdigit():
        return str(int(lower))

    return text