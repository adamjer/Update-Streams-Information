from pathlib import Path
import json
from json.decoder import JSONDecoder
import urllib.request
import requests
from requests.auth import HTTPBasicAuth 
import re
import zipfile
import os
from PIL import Image
import shutil
from getpass import getpass


class NoResolutionFound(Exception):
    """Base class for other exceptions"""
    pass

class NoGoldensResourceFound(Exception):
    """Base class for other exceptions"""
    pass

def selectNewestArtifact(artifacts):
	result = None
	for artifact in artifacts:
		if result == None:
			result = artifact
			continue
		if result["version"] < artifact["version"]:
			result = artifact
	return result

def selectGoldens(artifact):
	references = []
	for reference in artifact["artifactVersions"]:
		if "reference" in reference["name"]:
			references.append(reference)

	for result in references:
		if "reference_screenshots_for-common" in result["name"]:
			return result

	for result in references:
		if "reference_screenshots" in result["name"]:
			return result

	for result in references:
		if "reference_resources_for-common" in result["name"]:
			return result

	for result in references:
		if "reference_resources" in result["name"]:
			return result

	if references:
		return references[0]
	return references

def getArchiveName(artifactoryContent):
	for line in artifactoryContent:
		if ".zip" in line:
			break
	
	return re.search(r'.zip">.*</a>', line).group()[6:-4]

def getResolutions(path):
	resolutions = dict()
	for golden in os.listdir(path):
		im = None
		try:
			im = Image.open(Path(path, golden), "r")
			res = im.size
			if res not in resolutions:
				resolutions[res] = 1
			else:
				resolutions[res] = resolutions[res] + 1
		except Exception as e:
			print(f"\tINFO: {e}")
		finally:
			if im:
				im.close()
		
	if not resolutions:
		raise NoResolutionFound

	result = ""
	resolutionKeys = resolutions.keys()
	resolutionKeys = sorted(resolutionKeys, key=lambda item : item[0] * item[1])
	if len(resolutionKeys) == 1:
		result += f"{resolutionKeys[0][0]}x{resolutionKeys[0][1]}"
		return result

	for key in resolutionKeys:
		if resolutions[key] > 1:
			result += f"{key[0]}x{key[1]}, "

	if result != "":
		#delete ", " at the end of result
		return result[0:-2]

	#case for streams with all different frames resolution
	for key in resolutionKeys:
		result += f"{key[0]}x{key[1]}, "

	#delete ", " at the end of result
	return result[0:-2]

def getNewAttribute(resolution):
	return '{' + '"value": "' + resolution + '", ' + '"name": "gta.planning.item.resolution", ' + '"resolvedValue": "' + resolution + '", ' + '"typeId": 0, ' + '"unit": null, ' + '"prefixForParameters": null ' + '}'

def handleAttributes(stream, resolution, testItem, credentials):
	parameter = None
	login = credentials[0]
	password = credentials[1]

	for x in testItem["attributes"]:
		if x["name"] == "gta.planning.item.Resolution" or x["name"] == "Resolution" or x["name"] == "resolution" or x["name"] == "gta.planning.item.resolution":
			parameter = x
			break

	if parameter == None:
		#add new attribute
		temp = json.loads(getNewAttribute(resolution))
		testItem["attributes"].append(temp)

	elif parameter["name"] != "gta.planning.item.resolution":
		#update existing attribute
		parameter["value"] = resolution
		parameter["resolvedValue"] = resolution
		parameter["name"] = "gta.planning.item.resolution"

	elif parameter["value"] != resolution or parameter["resolvedValue"] != resolution:
		#update existing attribute
		parameter["value"] = resolution
		parameter["resolvedValue"] = resolution

	else:
		print(f"\tSUCCESS: {testItem['itemId']} actually contained proper resolution information")
		return

	#update Test Item
	updateResponse = requests.put(f"http://gta.intel.com/api/tp/v1/testitems/{testItem['key']}", headers={"Content-Type": "application/json", "Accept": "application/json"}, data=json.dumps(testItem), auth = HTTPBasicAuth(login, password))
	if updateResponse.status_code == 200:
		print(f"\tSUCCESS: {testItem['itemId']}: new attribute added, gta.planning.item.resolution = [{resolution}]")
	else:
		print(f"\tERROR: {testItem['itemId']}: status code = {updateResponse.status_code}\n\t\t{updateResponse.text}"),


def load_file(file, credentials):
	streams = json.loads(open(file, 'r').read())

	login = credentials[0]
	password = credentials[1]

	counter = -1
	for stream in streams["RESULT"]:
		global global_counter
		global_counter += 1
		counter += 1
		print(f"STREAM[{global_counter}] {file.name}[{counter}]: {stream['name']}")
		#choose resource
		for resource in stream["resources"]:
									      #SCATE2     GITS2       ABN-Trace   GITS        GfxBench DXVK
			if resource["itemId"] not in ["RES-3106", "RES-3111", "RES-3170", "RES-3110", "RES-143632"]:
				#resourceLink =
				#"http://gta.intel.com/api/res-mngr/resources/{}/versions".format(resource["itemId"])
				request = urllib.request.Request(url="http://gta.intel.com/api/res-mngr/resources/{}/versions".format(resource["itemId"]), method="GET")
				
				# create a password manager
				password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
				top_level_url = "http://gta.intel.com/"
				password_mgr.add_password(None, top_level_url, login, password)
				handler = urllib.request.HTTPBasicAuthHandler(password_mgr)
				opener = urllib.request.build_opener(handler)
				urllib.request.install_opener(opener)


				try:
					resourceWebResponse = urllib.request.urlopen(request)
					response = json.loads(resourceWebResponse.read())
				except:
					print(f"\tERROR: Couldn't get stream's {stream['name']} resource {resource['itemId']} info")
					continue

				request = urllib.request.Request(url=f"http://gta.intel.com/api/tp/v1/testitems/{stream['itemId']}", method="GET")
				try:
					testItemWebResponse = urllib.request.urlopen(request)
					testItem = json.loads(testItemWebResponse.read())
				except:
					print(f"\tERROR: Couldn't get stream's TI {stream['name'].strip()} stream['testId'] info")
					continue

				artifact = selectNewestArtifact(response)
				if artifact == None:
					print(f"\tERROR: No artifacts for Resource:{resource['itemId']} Artifact:{artifact['itemId']} {artifact['name']}")
					continue

				try:
					goldens = selectGoldens(artifact)
				except NoGoldensResourceFound:
					print(f"\tERROR: No goldens found for Resource:{resource['itemId']} Artifact:{artifact['itemId']} {artifact['name']}")
					handleAttributes(stream, "no goldens resource", testItem, credentials)
					continue

				request = urllib.request.Request(url=f"http://gfx-assets.igk.intel.com/artifactory/{goldens['buildName']}", method="GET")

				try:
					artifactoryWebResponse = urllib.request.urlopen(request)
					response = str(artifactoryWebResponse.read())
				except:
					print(f"\tERROR: Couldn't get goldens from artifactory {goldens['repositoryPath']} info")
					continue
				
				archiveName = getArchiveName(response.split())
				if archiveName == None:
					print(f"\tERROR: Couldn't get archive name {goldens['repositoryPath']}")
					continue

				#request =
				#urllib.request.Request(url=f"http://gfx-assets.igk.intel.com/artifactory/{goldens['buildName']}/{archiveName}",
				#method="GET")
				try:
					artifactoryWebResponse = requests.get(url=f"http://gfx-assets.igk.intel.com/artifactory/{goldens['buildName']}/{archiveName}", stream=True) #urllib.request.urlopen(request)
					#dataToWrite = artifactoryWebResponse.read()
				except:
					print(f"\tERROR: Couldn't connect with artifactory {goldens['repositoryPath']}")
					continue

				try:
					with open(Path(f"Archives/{stream['name'].strip()}.zip"), "wb") as f:
						for chunk in artifactoryWebResponse.iter_content(chunk_size = 500 * 1000 * 1024): #chunks 500MB
							f.write(chunk)
				except Exception as e:
					print(f"\tERROR: Couldn't save file to disk!")
					continue

				with zipfile.ZipFile(Path(f"Archives/{stream['name'].strip()}.zip"), 'r') as zip_ref:
					zip_ref.extractall(Path(f"Archives/{stream['name'].strip()}"))

				if os.path.exists(Path(f"Archives/{stream['name'].strip()}")):
					os.remove(Path(f"Archives/{stream['name'].strip()}.zip"))
				else:
					print("\tERROR: Archives not unzipped!")
					continue

				try:
					resolutions = getResolutions(Path(f"Archives/{stream['name'].strip()}"))
				except NoResolutionFound:
					print("\tERROR: Couldn't get resolutions from goldens!")
					handleAttributes(stream, "no goldens", testItem, credentials)
					continue

				try:
					shutil.rmtree(Path(f"Archives/{stream['name'].strip()}"))
				except:
					print("\tERROR: Deletion of unzipped goldens failed!")

				handleAttributes(stream, resolutions, testItem, credentials)

		print("--------END OF STREAM--------\n")			

def inputCredentials():
	login = input("Login: ")
	password = getpass("Password: ")
	
	return (login, password)

def load_files(path):
	credentials = inputCredentials()
	files = os.listdir(Path(path))
	global global_counter
	global_counter = -1
	for file in files:
		load_file(Path(path ,file), credentials)


archives = input("Streams location: ")
load_files(archives)


print("XXX========== END FILES ==========XXX")