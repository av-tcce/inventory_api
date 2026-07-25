import re

with open('static/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

def check_divs(start_id, end_id):
    start = html.find(start_id)
    end = html.find(end_id)
    section = html[start:end]
    div_starts = len(re.findall(r'<div\b[^>]*>', section))
    div_ends = len(re.findall(r'</div>', section))
    print(f"{start_id}: Starts: {div_starts}, Ends: {div_ends}, Diff: {div_starts - div_ends}")

check_divs("id=\"module-curvas\"", "<script>")
