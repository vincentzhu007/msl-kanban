"""Task ids the daily workflow may run, in schedule order.

The workflow copies this tuple into DAILY_SCHEDULED_TASKS. A dispatch names
one id and the select job emits only that id. all, an empty choice, and the
schedule emit the whole tuple. The first five ids stay ahead of the two
Qwen2.5-1.5B tasks.
"""

SCHEDULED = (
    'qwen25-05b-msl-w4a16-kirin9020',
    'qwen25-05b-msl-q30-kirin9020',
    'qwen3-4b-msl-s16s4-kirin9030',
    'qwen3-06b-msl-s16s4-kirin9030',
    'qwen25-05b-llama-q40-kirin9020',
    'qwen25-15b-msl-w4a16-kirin9020',
    'qwen25-15b-msl-q30-kirin9020',
)

ORIGINAL_FIVE = SCHEDULED[:5]


def select_tasks(event_name, requested):
    if event_name == 'workflow_dispatch' and requested and requested != 'all':
        if requested not in SCHEDULED:
            raise ValueError('refusing unknown daily task: ' + str(requested))
        return [requested]
    return list(SCHEDULED)
