import os
import time
import shutil

class DiskCleanup:
    def __init__(self):
        self.name_spaces: list(str) = list(os.environ.get("NAMESPACE_LIST", "dev,production,staging").split(","))
        self.parent_directory = os.environ.get("UPLOAD_DIRECTORY","/nfs/public/rw/enswbsites/")

    def delete_old_temp_directories(self, days: int = 7):
        threshold_time = time.time() - (days * 86400)

        deleted_dirs = []
        errors = []
        for name_space in self.name_spaces:
            vep_upload_directory = self.parent_directory + "/" + name_space + "/vep"
            try:
                for temp_dir in os.listdir(vep_upload_directory):
                    full_path = os.path.join(vep_upload_directory, temp_dir)
                    if os.path.isdir(full_path):
                        dir_mod_time = os.path.getmtime(full_path)

                        if dir_mod_time < threshold_time:
                            try:
                                print(f"Deleting: {full_path}")
                                shutil.rmtree(full_path)
                                deleted_dirs.append(full_path)
                            except Exception as e:
                                print(f"Error deleting {full_path}: {e}")
                                errors.append((full_path, str(e)))

            except Exception as e:
                print(f"Error accessing {vep_upload_directory}: {e}")
                errors.append((vep_upload_directory, str(e)))

        if deleted_dirs:
            print("\nDeleted Directories!")
        else:
            print("No directories were deleted.")

        if errors:
            print("\nErrors:")
            for path, error in errors:
                print(f"Error with {path}: {error}")


if __name__ == "__main__":
    DiskCleanup().delete_old_temp_directories()


