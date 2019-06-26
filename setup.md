# OrcaDetector setup

This UC Berkeley Master of Information in Data Science capstone project was developed by
[Spyros Garyfallos](mailto:spiros.garifallos@berkeley.edu ), [Ram Iyer](mailto:ram.iyer@berkeley.edu), and [Mike Winton](mailto:mwinton@berkeley.edu).

## 0. Provision a cloud GPU machine

### Using AWS

If using AWS, as assumed by these setup instructions, provision an Ubuntu 18.04 `p2.xlarge` instance.  It's got older GPUs (Tesla K80) but is much cheaper.  Make sure to upgrade the storage space (e.g. 500 GB).  Also, make sure to pick a prebuilt Deep Learning AMI during the first step of the provisioning process. The most current version as of writing is `Deep Learning AMI (Ubuntu) Version 23.0 - ami-058f26d848e91a4e8`. This will already have `docker` and `nvidia-docker` pre-installed and will save you a lot of manual installation "fun".

### Using IBM Cloud

Provision a server to run the training code. You can you this server as your development environment too.

Install the CLI, add your ssh public key, and get the key id
```
curl -fsSL https://clis.ng.bluemix.net/install/linux | sh
ibmcloud login
ibmcloud sl security sshkey-add LapKey --in-file ~/.ssh/id_rsa.pub
ibmcloud sl security sshkey-list
```

Provision a V100 using this key id

```
ibmcloud sl vs create \
    --datacenter=lon04 \
    --hostname=v100a \
    --domain=your.domain.com \
    --image=2263543 \
    --billing=hourly \
    --network 1000 \
    --key={YOUR_KEY_ID} \
    --flavor AC2_8X60X100 --san
```


Wait for the provisioning completion 
```
watch ibmcloud sl vs list
```

SSH on this host to setup the container.

```
ssh -i ~/.ssh/id_rsa {SERVER_IP}
```

Once there, allow TCP inbound on 32001 to use for exposing the dev container
```
ufw allow 32001/tcp
```

>Note:You'll need to check-in your public SSH key in the keys folder and modify the last layer of the dockerfile to get access to the container from VsCode

## 1. Set up required environment variables - UPDATE

Set the environment variable for MLFlow in your system's `~/.bashrc` file (or on a Mac, in your `~/.bash_profile` file):

```
TBD
```

After saving the file, type `source ~/.bashrc` to load the new variables into your environment.


## 2. Clone the project repo

If you haven't already, clone the project Git repo to your instance.  Doing so in your home directory is convenient, and this document assumes you have done so.

```
cd ~
git clone https://github.com/paloukari/OrcaDetector
```

## 3. Create the `orca_dev` Docker image

### GPU OPTION: Build our `orca_dev` base Docker image

In the project repo, `cd` into the `orca_detector` directory:

```
cd ~/OrcaDetector/orca_detector
```

Build the Docker image (this will take a while):

```
sudo docker build \
    -t orca_dev \
    -f Dockerfile.dev \
    --build-arg AWS_ID={YOUR_AWS_ID} \
    --build-arg AWS_SECRET={YOUR_AWS_SECRET} .
```

## 4. Launch an `orca_dev` Docker container

Run the `orca_dev` Docker container with the following args.  

> NOTE: update the host volume mappings (i.e. `~/OrcaDetector`) as appropriate for your machine in the following script:

```
sudo docker run \
    --rm \
    --runtime=nvidia \
    --name orca_dev \
    -ti \
    -e JUPYTER_ENABLE_LAB=yes \
    -v ~/OrcaDetector/results:/results \
    -p 8888:8888 \
    -p 4040:4040 \
    -p 32001:22 \
    orca_dev
```

You will see it listed as `orca_dev ` when you run `docker ps -a`.  

### Verify Keras can see the GPU

Once inside the container, try running:

```
nvidia-smi
```

### Verify that the `vggish` Keras model builds

Once inside the container, the following script should run to make sure we can instantiate the Keras model and load it's pretrained weights:

```
python3 vggish_model.py
```

If it was successful, you should see a Keras model summary.


### (REMOVE?) Verify that the `vggish` TF smoke test runs

Once inside the container, the following script should run an end-to-end check of the `vggish` pipeline:

```
python3 vggish/vggish_smoke_test.py
```

### (OPTIONAL) Launch Jupyter Lab in the container

After you've started the container as described above, if you want to _also_ open a Jupyter notebook (e.g. for development/debugging), issue this command:

```
docker exec -it orca_dev bash
```

Then in the Docker shell that opens, type:

```
jupyter lab --allow-root --port=8888 --ip=0.0.0.0
```

Then go to your browser and enter:

```
http://127.0.0.1:8888?token=<whatever token got displayed in the logs>
```

## 5. (Alternative) Manually setup the container for remote debugging

We need to setup the container to allow the same SSH public key. The entire section could be automated in the dockerfile. We can add our public keys in the repo and pre-authorize us at docker build.

To create a new key in Windows, run:

Powershell: 
```
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
ssh-keygen -t rsa -b 4096 
```

The key will be created here: %USERPROFILE%\.ssh

Inside the container, set the root password. We need this to copy the dev ssh pub key.
```
passwd root
```
Install SSH server
```
apt-get install openssh-server
systemctl enable ssh
```
Configure password login
```
vim /etc/ssh/sshd_config
```
Change these lines of /etc/ssh/sshd_config:
```
PasswordAuthentication yes
PermitRootLogin yes
```
Start the service
```
service ssh start
```

Now, you should be able to login from your dev environment using the password.
```
ssh root@{SERVER_IP} -p 32001
```

To add the ssh pub key in the container, from the dev environment run:

```
SET REMOTEHOST=root@{SERVER_IP}:32001
scp %USERPROFILE%\.ssh\id_rsa.pub %REMOTEHOST%:~/tmp.pub
ssh %REMOTEHOST% "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat /tmp/tmp.pub >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && rm -f /tmp/tmp.pub"
```

Test it works:
```
ssh -i ~/.ssh/id_rsa {SERVER_IP} -p 32001
```

Now, you can remove the password root access if you want.

In VsCode, install the Remote SSH extension.
Hit F1 and run VsCode SSH Config and enter 

```
Host V100
    User root
    HostName {SERVER_IP}
    Port 32001
    IdentityFile ~/.ssh/id_rsa
```
Hit F1 and select Remote-SSH:Connect to Host

Once in there, open the OrcaDetector folder, install the Python extension on the container (from the Vs Code extensions), select the python interpreter and start debugging.


## 6. Train the OrcaDetector

### Training

TBD

### Testing

TBD