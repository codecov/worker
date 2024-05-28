import os


def get_extension(filename: str) -> str:
    """
    Gets the file extension of the file without the dot
    """
    # At times file can be something like './index.js + 12 modules', only keep the real filepath
    filename = filename.split(" ")[0]
    # Retrieve the file extension with the dot
    _, file_extension = os.path.splitext(filename)
    # Return empty string if file has no extension
    if not file_extension or file_extension[0] != ".":
        return ""
    # Remove the dot in the extension
    file_extension = file_extension[1:]
    # At times file can be something like './index.js?module', remove the ?
    if "?" in file_extension:
        file_extension = file_extension.split("?")[0]

    return file_extension