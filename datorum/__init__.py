import os
from dotenv import dotenv_values

GeneralConfig = {
    **os.environ,
    **dotenv_values(".env")
}
