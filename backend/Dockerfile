FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-c"]

# ---------- 기본 도구 ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl wget git build-essential ca-certificates gnupg2 lsb-release locales \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*
ENV LANG=en_US.UTF-8

# ---------- ROS2 Jazzy (apt) ----------
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
        > /etc/apt/sources.list.d/ros2.list \
    && apt-get update && apt-get install -y --no-install-recommends \
        ros-jazzy-desktop ros-dev-tools \
    && rm -rf /var/lib/apt/lists/* \
    && rosdep init && rosdep update

# ---------- Miniconda ----------
RUN curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh \
    && bash /tmp/miniconda.sh -b -p /opt/conda \
    && rm /tmp/miniconda.sh
ENV PATH=/opt/conda/bin:$PATH

# defaults 채널(pkgs/main, pkgs/r) 이용약관 동의 없이는 conda env create가 비대화형에서 막힘
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main \
    && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# solve 속도 때문에 classic conda solver 대신 mamba 사용
RUN conda install -n base -c conda-forge mamba -y

# ---------- ML 환경 (Pointcept libs/pointops, libs/pointgroup_ops가 필요해서 Pointcept를 먼저 클론) ----------
WORKDIR /opt
RUN git clone --depth 1 https://github.com/Pointcept/Pointcept.git
WORKDIR /opt/Pointcept

# 한 번에 solve 안 돼서 단계별로 나눔: 코어(pytorch+cuda)부터 좁게 solve
RUN mamba create -n unified_env_ver2 -y \
        -c pytorch -c "nvidia/label/cuda-12.4.4" -c nvidia -c conda-forge \
        python=3.12 pip cuda conda-forge::cudnn gcc=13.2 gxx=13.2 \
        pytorch=2.5.0 torchvision=0.20.0 torchaudio=2.5.0 pytorch-cuda=12.4 ninja

# 나머지 conda 패키지들 추가 (한 번에 넣으니 solve가 오래 걸려서 3그룹으로 분할)
RUN mamba install -n unified_env_ver2 -y -c conda-forge \
        sparsehash h5py "pyyaml>=5.3.1" "requests>=2.23.0" tqdm addict termcolor \
        "psutil>=5.8.0" "filelock>=3.16.1"

RUN mamba install -n unified_env_ver2 -y -c conda-forge \
        "numpy=1.26.0" scipy "matplotlib>=3.3.0" "pillow>=9.0.0" "einops>=0.6.1" plyfile ftfy regex \
        "scikit-learn>=1.3.2"

RUN mamba install -n unified_env_ver2 -y -c conda-forge \
        black open3d tensorboard tensorboardx wandb mlflow yapf timm

ENV CONDA_ENV=/opt/conda/envs/unified_env_ver2
# CUDA 툴킷을 conda로 설치했기 때문에 torch cpp_extension이 nvcc 찾을 수 있게 경로 지정
ENV CUDA_HOME=$CONDA_ENV

# pip 패키지 대다수 (requirements_pip.txt)
COPY requirements_pip.txt /opt/Pointcept/requirements_pip.txt
RUN $CONDA_ENV/bin/pip install -r requirements_pip.txt

# git+ 소스 설치 (개별 실패 지점 확인 쉽게 하려고 분리)
RUN $CONDA_ENV/bin/pip install git+https://github.com/octree-nn/ocnn-pytorch.git
RUN $CONDA_ENV/bin/pip install git+https://github.com/openai/CLIP.git
RUN $CONDA_ENV/bin/pip install "s2wrapper@git+https://github.com/bfshi/scaling_on_scales"

# flash-attn: GPU 없는 이 PC에서는 빌드해도 검증 불가 + 소스 컴파일이 너무 오래 걸려서 제외.
# GPU PC에서 이미지 받은 뒤 아래 명령어로 별도 설치 예정:
#   pip install flash-attn --no-build-isolation

# nv/target 등 libcu++ 헤더가 core cuda 메타패키지에 안 딸려와서 별도 설치
RUN mamba install -n unified_env_ver2 -y -c "nvidia/label/cuda-12.4.4" -c nvidia cuda-cccl
# 위 헤더들이 include/가 아니라 targets/x86_64-linux/include(/cccl)/ 밑에 깔려서 g++가 못 찾음 -> CPATH에 추가
ENV CPATH=$CONDA_ENV/targets/x86_64-linux/include:$CONDA_ENV/targets/x86_64-linux/include/cccl:$CPATH

# 이 PC엔 GPU가 없어서 torch가 CUDA 아키텍처 자동 감지를 못 함 -> 직접 지정
# (Pascal~Hopper까지 폭넓게 잡아둠, GPU PC의 정확한 GPU 모델 확인되면 좁혀도 됨)
ENV TORCH_CUDA_ARCH_LIST="6.0;6.1;7.0;7.5;8.0;8.6;8.9;9.0"

# Pointcept 로컬 확장 모듈 (CUDA 커스텀 op) - CUDA/C++ 컴파일이 필요해서 conda activate로
# 컴파일러(gcc=13.2)/CUDA 관련 활성화 스크립트까지 제대로 걸리게 함 (build isolation은 끔)
RUN source /opt/conda/etc/profile.d/conda.sh && conda activate unified_env_ver2 \
    && pip install --no-build-isolation ./libs/pointops
RUN source /opt/conda/etc/profile.d/conda.sh && conda activate unified_env_ver2 \
    && pip install --no-build-isolation ./libs/pointgroup_ops

# ---------- pinky_pro (ROS2 워크스페이스) ----------
RUN mkdir -p /ros2_ws/src
WORKDIR /ros2_ws
RUN git clone https://github.com/pinklab-art/pinky_pro.git src/pinky_pro
RUN . /opt/ros/jazzy/setup.bash \
    && export PATH=/usr/bin:$PATH \
    && apt-get update \
    && rosdep install --from-paths src --ignore-src -r -y \
    && rm -rf /var/lib/apt/lists/* \
    && colcon build

# ---------- supervisord ----------
RUN apt-get update && apt-get install -y --no-install-recommends supervisor \
    && rm -rf /var/lib/apt/lists/*

# ---------- 우리 코드 ----------
WORKDIR /workspace
# TODO: segmentation_node.py, vlm_rl_corrector_node.py 등 실제 스크립트로 교체
# COPY ./app /workspace

COPY entrypoint.sh /entrypoint.sh
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
RUN chmod +x /entrypoint.sh

# flash-attn: 원래는 GPU PC에서 별도 설치 예정이었으나, 이 이미지에 미리 빌드해 넣어달라는 요청으로 포함.
# GPU 없는 이 PC라 컴파일만 하고 동작 검증은 GPU PC에서 필요. 병렬 컴파일 메모리 부담 커서 MAX_JOBS 제한.
RUN source /opt/conda/etc/profile.d/conda.sh && conda activate unified_env_ver2 \
    && MAX_JOBS=2 pip install flash-attn --no-build-isolation

# nvitop: GPU 사용률 모니터링용. requirements_pip.txt에 안 넣고 맨 끝에 독립 레이어로 둠 --
# 거기 넣으면 그 아래(git+ 설치들 ~ 방금 위 flash-attn 컴파일까지) 캐시가 전부 깨짐.
# nvidia-ml-py는 requirements_pip.txt에 이미 있어서 nvitop이 그걸 그대로 재사용함.
RUN source /opt/conda/etc/profile.d/conda.sh && conda activate unified_env_ver2 \
    && pip install nvitop

# RTX5080(Blackwell, sm_120)은 위에서 conda로 깐 PyTorch 2.5.0(cu124)이 지원 안 함
# ("CUDA error: no kernel image is available for execution on the device").
# cu128 빌드로 재설치 -- 마찬가지로 맨 끝 독립 레이어라 재빌드해도 앞 캐시(flash-attn
# 컴파일 포함) 그대로 재사용됨. pointops/pointgroup_ops(Pointcept)는 이 업그레이드 후에도
# 정상 동작 확인됨, flash-attn만 ABI 불일치로 깨짐(재컴파일 필요, 아직 안 함).
RUN source /opt/conda/etc/profile.d/conda.sh && conda activate unified_env_ver2 \
    && pip install --index-url https://download.pytorch.org/whl/cu128 \
       torch torchvision torchaudio --upgrade

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
