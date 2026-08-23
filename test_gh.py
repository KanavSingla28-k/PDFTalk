import urllib.request, json
res = json.loads(urllib.request.urlopen('https://api.github.com/repos/KanavSingla28-k/PDFTalk/actions/runs').read())
for r in res["workflow_runs"][:3]:
    print(f'{r["status"]} - {r["conclusion"]} - {r["head_commit"]["message"]}')
