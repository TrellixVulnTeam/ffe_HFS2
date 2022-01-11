"""ibm: 上传文件到 IBM COS
dependencies = ["ibm-cos-sdk"]

https://github.com/ahui2016/ffe/raw/main/recipes/ibm.py
"""

# 每个插件都应如上所示在文件开头写简单介绍，以便 "ffe install --peek" 功能窥视插件概要。

"""
- 参考1 (重要) https://cloud.ibm.com/docs/cloud-object-storage?topic=cloud-object-storage-python
- 参考2 https://github.com/IBM/ibm-cos-sdk-python
- 参考3 https://cloud.ibm.com/apidocs/cos/cos-compatibility?code=python

- 注册一个 cloud.ibm.com 账号
- 启用 IBM Cloud Object Storage 并且创建一个 bucket
- pip install ibm-cos-sdk
- Gather required information (收集必要参数) https://cloud.ibm.com/docs/cloud-object-storage?topic=cloud-object-storage-python#python-prereqs
- 把相关信息填写到 ffe-config.toml (参考 https://github.com/ahui2016/ffe/blob/main/examples/ffe-config.toml)
"""

import ibm_boto3
from ibm_botocore.client import Config, ClientError
import tomli
import arrow
from pathlib import Path
from ffe.model import Recipe, ErrMsg, get_bool, must_exist, must_files, names_limit
from ffe.util import app_config_file

MB = 1024 * 1024

# set 5 MB chunks
part_size = 5 * MB

# set default threadhold to 15 MB
default_limit = 15


# 每个插件都必须继承 model.py 里的 Recipe
class IBM(Recipe):
    @property  # 必须设为 @property
    def name(self) -> str:
        return "ibm"

    @property  # 必须设为 @property
    def help(self) -> str:
        return """upload to IBM COS"""

    @property  # 必须设为 @property
    def default_options(self) -> dict:
        return dict(
            add_prefix=True,
            size_limit=0,
            names=[],
        )

    def validate(self, names: list[str], options: dict) -> ErrMsg:
        """初步检查参数（比如文件数量与是否存在），并初始化以下项目：

        - self.item_name
        - self.size_limit
        - self.filename
        """
        # 要在 dry_run, exec 中确认 is_validated
        self.is_validated = True

        # 优先采用 options 里的 names, 方便多个任务组合。
        options_names = options.get("names", [])
        if options_names:
            names = options_names

        # set self.filename
        names, err = names_limit(names, 1, 1)
        if err:
            return err
        self.filename = names[0]

        err = must_exist(names)
        if err:
            return err
        err = must_files(names)
        if err:
            return err

        # set self.item_name
        add_prefix, err = get_bool(options, "add_prefix")
        if err:
            return err
        self.item_name = Path(self.filename).name
        if add_prefix:
            prefix = f"{arrow.now().format('YYYYMMDDHHmmss')}-"
            self.item_name = prefix + self.item_name

        # set self.size_limit
        limit = options.get("size_limit", 0)
        if not limit:
            limit = 15
        self.size_limit = limit * MB

        return ""

    def dry_run(self) -> ErrMsg:
        assert self.is_validated, "在执行 dry_run 之前必须先执行 validate"
        print(f"Starting transfer {self.item_name} to IBM COS\n")
        print("本插件涉及第三方服务，因此无法继续预测执行结果。")
        return ""

    def exec(self) -> ErrMsg:
        assert self.is_validated, "在执行 exec 之前必须先执行 validate"
        cfg_ibm = get_config()
        cos = get_ibm_resource(cfg_ibm)
        upload(
            cos, cfg_ibm["bucket_name"], self.item_name, self.size_limit, self.filename
        )
        return ""


__recipe__ = IBM


def get_config() -> dict:
    with open(app_config_file, "rb") as f:
        config = tomli.load(f)
        return config["ibm"]


def get_ibm_resource(cfg_ibm: dict):
    return ibm_boto3.resource(
        "s3",
        ibm_api_key_id=cfg_ibm["ibm_api_key_id"],
        ibm_service_instance_id=cfg_ibm["ibm_service_instance_id"],
        config=Config(signature_version="oauth"),
        endpoint_url=cfg_ibm["endpoint_url"],
    )


# https://cloud.ibm.com/docs/cloud-object-storage?topic=cloud-object-storage-python#python-examples-multipart
def upload(cos, bucket_name: str, item_name: str, size_limit: int, file_path: str):
    try:
        print(f"Starting transfer {item_name} to IBM COS\n")

        # set the transfer threshold and chunk size
        transfer_config = ibm_boto3.s3.transfer.TransferConfig(
            multipart_threshold=size_limit, multipart_chunksize=part_size
        )

        # the upload_fileobj method will automatically execute a multi-part upload
        # in 5 MB chunks for all files over 15 MB
        with open(file_path, "rb") as file_data:
            cos.Object(bucket_name, item_name).upload_fileobj(
                Fileobj=file_data, Config=transfer_config
            )

        print("Transfer Complete!\n")
    except ClientError as be:
        print("CLIENT ERROR: {0}\n".format(be))
    except Exception as e:
        print("Unable to complete multi-part upload: {0}".format(e))
