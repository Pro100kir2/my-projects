import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

payload={
  'scope': 'GIGACHAT_API_PERS'
}
headers = {
  'Content-Type': 'application/x-www-form-urlencoded',
  'Accept': 'application/json',
  'RqUID': 'c6feb299-8a12-45d7-be50-2e57a390277b',
  'Authorization': 'Basic OTc2OWFkMjEtZGZkZC00ZGRjLTgyNDctMTMxODliMDY0YTM3OjRiNWFhY2RkLWU0YTktNDNhMy1iNjk5LWU1MTY0NmIxNWM0YQ=='
}

response = requests.request("POST", url, headers=headers, data=payload, verify=False)

print(response.text)