from setuptools import setup

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='prometheus-qbittorrent-exporter',
    packages=['qbittorrent_exporter'],
    version='1.1.0',
    long_description=long_description,
    long_description_content_type="text/markdown",
    description='Prometheus exporter for qbittorrent',
    author='Esteban Sanchez',
    author_email='esteban.sanchez@gmail.com',
    url='https://github.com/esanchezm/prometheus-qbittorrent-exporter',
    download_url='https://github.com/esanchezm/prometheus-qbittorrent-exporter/archive/1.1.0.tar.gz',
    keywords=['prometheus', 'qbittorrent'],
    classifiers=[],
    python_requires='>=3',
    install_requires=['qbittorrent-api==2020.9.9', 'prometheus_client==0.8.0', 'python-json-logger==0.1.5'],
    entry_points={
        'console_scripts': [
            'qbittorrent-exporter=qbittorrent_exporter.exporter:main',
        ]
    }
)
