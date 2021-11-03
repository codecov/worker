from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = copy_metadata("opentelemetry-sdk")
