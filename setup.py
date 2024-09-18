from setuptools import find_packages, setup

setup(
    name="telegram_dump",
    include_package_data=True,
    install_requires=[
        "telethon",
        "cryptg",
        "SQLAlchemy",
        "ConfigArgParse",
        "tqdm",
        "exif",
    ],
    extras_require={
        "tests": ["pytest", "pytest-cov", "pytest-json-report"],
        "dev": ["black", "mypy", "pydocstyle", "pylint", "flake8"],
    },
    entry_points={
        "console_scripts": [
            "telegram-dump=telegram_dump.cli:telegram_dump",
        ]
    },
    packages=find_packages(where="src/"),
    package_dir={
        "": "src",
    },
)
