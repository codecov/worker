

# Interface class for interfacing with codecov's underlying storage layer
class BaseStorageService(object):

    def client(self):
        return self.minio_client if self.minio_client else None

    def create_root_storage(self, bucket_name='archive', region='us-east-1'):
        """
            Creates root storage (or bucket, as in some terminologies)

        Args:
            bucket_name (str): The name of the bucket to be created (default: {'archive'})
            region (str): The region in which the bucket will be created (default: {'us-east-1'})

        Raises:
            NotImplementedError: If the current instance did not implement this method
            BucketAlreadyExistsError: If the bucket already exists
        """
        raise NotImplementedError()

    def write_file(self, bucket_name, path, data, reduced_redundancy=False, gzipped=False):
        """
            Writes a new file with the contents of `data`
            (What happens if the file already exists?)


        Args:
            bucket_name (str): The name of the bucket for the file to be created on
            path (str): The desired path of the file
            data (str): The data to be written to the file
            reduced_redundancy (bool): Whether a reduced redundancy mode should be used (default: {False})
            gzipped (bool): Whether the file should be gzipped on write (default: {False})

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        raise NotImplementedError()

    def append_to_file(self, bucket_name, path, data):
        """
            Appends more content to the file `path`
            (What happens if the file doesn't exist?)

        Args:
            bucket_name (str): The name of the bucket for the file lives
            path (str): The desired path of the file
            data (str): The data to be appended to the file

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        raise NotImplementedError()

    def read_file(self, bucket_name, path):
        """Reads the content of a file

        Args:
            bucket_name (str): The name of the bucket for the file lives
            path (str): The path of the file

        Raises:
            NotImplementedError: If the current instance did not implement this method
            FileNotInStorageError: If the file does not exist

        Returns:
            bytes : The contents of that file, still encoded as bytes
        """
        raise NotImplementedError()

    def delete_file(self, bucket_name, path):
        """Deletes a single file from the storage (what happens if the file doesnt exist?)

        Args:
            bucket_name (str): The name of the bucket for the file lives
            path (str): The path of the file to be deleted

        Raises:
            NotImplementedError: If the current instance did not implement this method
            FileNotInStorageError: If the file does not exist

        Returns:
            bool: True if the deletion was succesful
        """
        raise NotImplementedError()

    def delete_files(self, bucket_name, paths=[]):
        """Batch deletes a list of files from a given bucket
            (what happens to the files that don't exist?)

        Args:
            bucket_name (str): The name of the bucket for the file lives
            paths (list): A list of the paths to be deletes (default: {[]})

        Raises:
            NotImplementedError: If the current instance did not implement this method

        Returns:
            list: A list of booleans, where each result indicates whether that file was deleted
                successfully
        """
        raise NotImplementedError()

    def list_folder_contents(self, bucket_name, prefix=None, recursive=True):
        """List the contents of a specific folder

        Args:
            bucket_name (str): The name of the bucket for the file lives
            prefix: The prefix of the files to be listed (default: {None})
            recursive: Whether the listing should be recursive (default: {True})

        Raises:
            NotImplementedError: If the current instance did not implement this method
        """
        raise NotImplementedError()
