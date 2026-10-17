# GPU image for Nebius VMs. Build: docker build -t muffle:dev .
# Run:   docker run --gpus all -it -v $PWD/data:/app/data muffle:dev make fl GPU=0
FROM nvcr.io/nvidia/pytorch:24.10-py3

WORKDIR /app
COPY requirements.txt requirements-dev.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .
RUN pip install --no-cache-dir -e .

# torch is already in the base image; point the Makefile at the system python
ENV VENV=/usr
CMD ["bash"]
