import re

def count(start_str, end_str):
    with open('static/index.html', 'r', encoding='utf-8') as f:
        html = f.read()
    start = html.find(start_str)
    end = html.find(end_str) if end_str else len(html)
    section = html[start:end]
    return len(re.findall(r'<div\b[^>]*>', section)), len(re.findall(r'</div>', section))

modules = [
    ('id="module-distribucion"', 'id="module-sabana"'),
    ('id="module-sabana"', 'id="module-solicitud-unidades"'),
    ('id="module-solicitud-unidades"', 'id="module-outlet"'),
    ('id="module-outlet"', 'id="module-devolucion"'),
    ('id="module-devolucion"', 'id="module-sales-analytics"'),
    ('id="module-sales-analytics"', 'id="module-agotados"'),
    ('id="module-agotados"', 'id="module-clasificacion"'),
    ('id="module-clasificacion"', 'id="module-reportes"'),
    ('id="module-reportes"', 'id="module-trivia"'),
    ('id="module-trivia"', 'id="module-ajustes"'),
    ('id="module-ajustes"', 'id="module-curvas"'),
    ('id="module-curvas"', '<script>')
]

for s, e in modules:
    st, en = count(s, e)
    print(f'{s}: Starts: {st}, Ends: {en}, Diff: {st - en}')
