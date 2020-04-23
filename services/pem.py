from shared.config import load_file_from_path_at_config

loaded_pems = None

pem_paths = {
    "github": ("github", "integration", "pem"),
    "github_enterprise": ("github_enterprise", "integration", "pem"),
}


def get_pem(pem_name: str) -> str:
    path = pem_paths[pem_name]
    return load_file_from_path_at_config(*path)
