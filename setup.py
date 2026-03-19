from setuptools import setup, find_packages

setup(
    name="captureAIshi",
    version="0.1.0",
    description="Cross-engine game capture framework for released games (UE5/Unity)",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "numpy>=1.21.0",
        "Pillow>=9.0.0",
        "flask>=2.0.0",
        "mss>=6.0.0",
    ],
    entry_points={
        "console_scripts": [
            "captureAIshi=main:main",
            "captureAIshi-gui=gui:main",
        ],
    },
)
