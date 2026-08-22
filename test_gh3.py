import urllib.request, json
res = json.loads(urllib.request.urlopen('https://api.github.com/repos/KanavSingla28-k/PDFTalk/actions/runs').read())
run_id = res['workflow_runs'][0]['id']
jobs = json.loads(urllib.request.urlopen(f'https://api.github.com/repos/KanavSingla28-k/PDFTalk/actions/runs/{run_id}/jobs').read())
failed_job = [j for j in jobs['jobs'] if j['conclusion'] == 'failure'][0]
req = urllib.request.Request(f'https://api.github.com/repos/KanavSingla28-k/PDFTalk/actions/jobs/{failed_job["id"]}/logs')
try:
    print(urllib.request.urlopen(req).read().decode('utf-8')[-3000:])
except Exception as e:
    print(e)
