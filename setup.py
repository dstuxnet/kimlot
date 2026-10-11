from setuptools import setup

setup(
    name="kimlot",
    version="1.0.0",
    py_modules=["kimlot"],
    entry_points={
        "console_scripts": [
            "kimlot=kimlot:main",
        ],
    },
)
