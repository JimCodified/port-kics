import json
import os
import sys
import requests
import time

base_delay = 1  # 1 second
max_retries = 5
max_delay = 32
API_URL = 'https://api.getport.io/v1'

def make_api_request(query, headers):
    response = requests.post(f'{API_URL}/blueprints/{query["identifier"]}/entities?upsert=true&merge=true&create_missing_related_entities=true', json=query, headers=headers)
    pass

def retry_with_exponential_backoff(query, headers):
    attempt = 0
    delay = base_delay
    
    while attempt < max_retries:
        try:
            result = make_api_request(query, headers)
            return result
        except Exception as e:
            attempt += 1
            if attempt >= max_retries:
                raise e
            sleep_time = min(delay * (2 ** attempt), max_delay)
            print(f"Attempt {attempt} failed. Retrying in {sleep_time:.2f} seconds...")
            time.sleep(sleep_time)
    raise Exception("All retry attempts failed.")

def get_access_token():
    """
    Retrieves an access token from Port's API.

    Returns:
        str: The access token.
    """
    CLIENT_ID = os.getenv("PORT_CLIENT_ID")
    CLIENT_SECRET = os.getenv("PORT_CLIENT_SECRET")

    credentials = {'clientId': CLIENT_ID, 'clientSecret': CLIENT_SECRET}

    token_response = requests.post(f'{API_URL}/auth/access_token', json=credentials)
    print(token_response.json())
    return token_response.json()['accessToken']


def parse_kics_results(file_path, repo_name):
    """
    Parses KICS results.json file to extract findings and files.

    Args:
        file_path (str): Path to the results.json file that KICS creates.

    Returns:
        dict: A single entity with all the findings.

    Future consideration: Parse the results.json file to get the findings per file and
        send to Port as separate entities + file entities. 

    Data structure:
      entity:
        mappings:
          identifier: <file>.query_id
          title: <file>.query_name
          blueprint: '"kicsScan"'
          properties:
            category: <file>.category
            cloud_provider: <file>.cloud_provider
            description: <file>.description
            files: <file>.files
            severity: <file>.severity
            platform: <file>.platform
            url: <file>.url
    """
    entities = []

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            content = json.load(file)
            
            for query in content["queries"]:
                entities.append({
                    "identifier": query["query_id"],
                    "title": query["query_name"],
                    "blueprint": "kicsScan",
                    "properties": {
                        "category": query["category"],
                        "cloud_provider": query["cloud_provider"],
                        "description": query["description"],
                        "files": query["files"],
                        "severity": query["severity"],
                        "platform": query["platform"],
                        "url": repo_name
                    }
                })

    except FileNotFoundError:
        print(f"Error: KICS result file not found at {file_path}")
    except Exception as e:
        print(f"Error parsing file: {e}")

    return entities

def create_service_entity(repo_name, query_ids):
    """
    Creates a service entity and connects it to its dependencies.

    Args:
        repo_name (str): The repository name (without the organization).
        dependencies (list): A list of dependency identifiers.

    Returns:
        dict: A service entity formatted for Port's BULK_UPSERT.
    """
    return {
        "identifier": repo_name,
        "blueprint": "service",
        "relations": {
            "kicsScan": query_ids  # Array of KICS query identifiers
        }
    }

def main():
    kics_results = sys.argv[1]
    if not kics_results:
        raise ValueError("Must include the path to the KICS results file as an argument.")

    # get the access token
    access_token = get_access_token()
    headers = {
        'Authorization': f'Bearer {access_token}'
    }

    # Extract the repository name from GITHUB_REPOSITORY (e.g., org/repo -> repo)
    full_repo_name = os.getenv("GITHUB_REPOSITORY", "org/default-repo")
    repo_name = full_repo_name.split("/")[-1]
    
    # Parse the KICS results file
    results = parse_kics_results(kics_results, repo_name)

    # Collect query identifiers for relations
    query_ids = [q["identifier"] for q in results]

    # Create the service entity
    service_entity = create_service_entity(repo_name, query_ids)
    # upsert svc entity - Note the ?upsert=true&merge=true query parameters
    response = requests.post(f'{API_URL}/blueprints/{service_entity["identifier"]}/entities?upsert=true&merge=true&create_missing_related_entities=true', json=service_entity, headers=headers)

    # upsert the queries with some API rate limit handling
    for query in results:
        retry_with_exponential_backoff(query, headers)

    # Output the result in JSON format for Port
    #print(json.dumps(all_entities, indent=2))

if __name__ == "__main__":
    main()