#!/usr/bin/env python3
"""Execute all Python cells locally and retain execution outputs in the notebooks.

Uses downloaded snapshot data offline; this does not claim a hosted Colab run.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
os.environ['ALETHEIA_DATA_DIR'] = str(ROOT/'backend/datasets/research')
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'

def main():
    report = []
    for filename in ['Aletheia_Multisource_Relevance_Colab.ipynb','Aletheia_Scientific_Stance_Colab.ipynb']:
        path=ROOT/'colab'/filename
        notebook=json.loads(path.read_text())
        context={'__name__':'__main__'}
        count=0
        started=time.monotonic()
        with tempfile.TemporaryDirectory(prefix='aletheia-notebook-') as directory:
            previous=Path.cwd()
            try:
                os.chdir(directory)
                for cell in notebook['cells']:
                    if cell['cell_type']!='code': continue
                    count+=1
                    stdout=io.StringIO()
                    with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stdout):
                        exec(compile(''.join(cell['source']),f'{filename}:cell-{count}','exec'),context)
                    cell['execution_count']=count
                    cell['outputs']=[{'output_type':'stream','name':'stdout','text':stdout.getvalue().splitlines(True)}]
                    if 'svg' in context and 'svg =' in ''.join(cell['source']):
                        cell['outputs'].append({'output_type':'display_data','metadata':{},'data':{'image/svg+xml':context['svg']}})
                assert context['archive'].exists()
            finally:
                os.chdir(previous)
        notebook['metadata']['aletheia_validation']={'environment':'local Python; all code cells executed against downloaded snapshot; not hosted Colab','code_cells':count}
        path.write_text(json.dumps(notebook,indent=2)+'\n')
        report.append({'notebook':filename,'code_cells':count,'seconds':round(time.monotonic()-started,2),'status':'passed'})
        print(report[-1],flush=True)
    (ROOT/'colab/validation-results.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__': main()
