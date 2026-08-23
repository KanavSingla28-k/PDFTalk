import urllib.request, json
res = json.loads(urllib.request.urlopen('https://api.github.com/repos/KanavSingla28-k/PDFTalk/actions/runs').read())
run_id = res['workflow_runs'][0]['id']
jobs = json.loads(urllib.request.urlopen(f'https://api.github.com/repos/KanavSingla28-k/PDFTalk/actions/runs/{run_id}/jobs').read())
for j in jobs['jobs']:
    if j['conclusion'] == 'failure':
        print(j['name'], j['conclusion'])
        for s in j['steps']:
            if s['conclusion'] == 'failure':
                print('  FAILED STEP:', s['name'])
