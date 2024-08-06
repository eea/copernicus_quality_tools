# EEA CLMS QC Tool

The application is composed of:
* Front-end user interface, alias web console;
* Worker Service;

# Documentation

Documentation of the QC tool, and specification of supported QA checks is available at https://github.com/eea/copernicus_quality_tools/wiki

# Reporting Issues

Please report any issues in the QC tool via GitHub:

* Go to https://github.com/eea/copernicus_quality_tools/issues and click *New Issue*.
* Sign-in with your GitHub account (or create a new GitHub account if you don't have one).
* Describe your issue. When describing an issue, please include the QC tool version and steps to reproduce.
* The development team will investigate the issue and get back to you.

# Prerequisities

* docker version 1.13 or higher, see https://docs.docker.com/install/linux/docker-ce/ubuntu/;
* docker-compose 1.21 or higher, see https://docs.docker.com/compose/install/#install-compose;

* Note: docker-compose version 3 file format is used. In case of errors, please upgrade to a newer version.

* For installation on Windows, see [docker/NOTES.windows](docker/NOTES.windows.md).

# Run the application

(1) Go to the [latest release](https://github.com/eea/copernicus_quality_tools/releases)

(2) Download the file `docker-compose.service_provider.yml`

(3) (Optional) Adjust the file `docker-compose.service_provider.yml` in accord with your environment.  For example see [docker/docker-compose.igor.yml](docker/docker-compose.igor.yml).  The environment variables are described in [docker/NOTES.environ.txt](docker/NOTES.environ.txt).  There is also `docker-compose.eea.yml` prepared targeting eea infrastructure with submission feature enabled.

(4) Run the application

```
sudo docker-compose -f ./docker-compose.service_provider.yml -p qc_tool_app up --scale worker=4
```

(5) You can reach the web console at any host address and port 8000.  For example, if you run the browser at the same host as docker containers, you can reach the application at http://localhost:8000.

(6) For initial signing in use user name `guest` and password `guest`.

(7) To upgrade to a new release, run:
```
sudo docker-compose -f ./docker-compose.service_provider.yml -p qc_tool_app pull
```
This will instruct docker to re-download the latest QC tool release images from docker hub repository.

# For developers

If you want to propagate your local source code into running containers you may apply docker bind mount.
Such a way you overlay the source code already built in the image at `/usr/local/src/copernicus_quality_tools`.
For advice see the example docker compose configuration [docker-compose.igor.yml](docker/docker-compose.igor.yml).

There are already some automated tests at `src/qc_tool/test`.
See the instructions in [NOTES.txt](src/qc_tool/test/NOTES.txt).

The qc_tool_frontend service uses sqlite database originally located at `/var/lib/qc_tool/frontend.sqlite`.
The initial database structure is made during docker build.
The `service_provider` and `eea` configurations use named volumes for persisting such database.
You are free to copy the database to other persistent location, however you must ensure setting up FRONTEND_DB_PATH properly.

# Demo installation

The service is publicly available at: https://qc-copernicus.eea.europa.eu/ Demo login is user: guest, password: guest.

# Product definitions

QA check configurations for Copernicus products are defined in the [product_definitions](product_definitions) directory. Each product definition .json file contains a list of parametrized checks. For QC tool setup with editable product definitions, see instructions in [docker/NOTES.product_definitions](docker/NOTES.product_definitions.md).



# Upgrade of the EEA QC TOOL instance
## Getting a VPN connection to the EEA:

1. Ask the EEA technical department (either try [andrei.cenja@eea.europa.eu](mailto:andrei.cenja@eea.europa.eu) or [adrian.Dascalu@eea.europa.eu](mailto:adrian.Dascalu@eea.europa.eu), or ask your EEA partner for a more up-to-date contact) for an openVPN package containing:
    - security keys (*tls.key, *.p12)
    - configuration file (*.ovpn)
    - certificate password
2. Set up your wikid client and request token validation:
    
    Depending on the chosen platform, you will install the wikid client from the "Play Store" or the "iTunes App Store". Use *WiKID Token 64* for iPhones or *WiKID Enterprise Token 4.0* for Android.  For PC based software tokens one would use a client from [https://www.wikidsystems.com/downloads/software-token-clients/](https://www.wikidsystems.com/downloads/software-token-clients/)
    
    When the client is fired-up for the first time it asks for a password to be set (to access the software token).
    
    - It will then tell you to add a new domain. Enter: "217074209204". Use of an asterisk in front of the numbers on phone clients used to be needed to force the use of "dns before IP" option, but recent experience shows that it is not needed anymore.
    - Select a pin that you will remember
    - It will then show a registration code.
    
    Write or call the "EEA [Helpdesk":mailto:helpdesk@eea.europa.eu](mailto:Helpdesk%22:mailto:helpdesk@eea.europa.eu) to have your registration validated and to supply a username (will also be used for your OpenVPN access). Have the Registration Code ready when calling or don't forget to mention it in your mail to helpdesk.
    *Please keep in mind that wikid request expires in one hour and is mandatory to validate with EEA Helpdesk.*
    

## Connecting to the EEA VPN itself in Linux terminal

- Install OpenVPN if you don't already have it: (sudo apt install openvpn easy-rsa)
- Cd to the directory with your security keys and configuration file (e.g.: cd /home/jtomicek/eea_vpn)
- Initialize the connection using the openvpn tool and the .ovpn configuration file (sudo openvpn --config <filename>.ovpn)
- You will be prompted for username Auth Username (same as for eionet), Auth Password (from wikid) and Private Key Password (certificate password).

## Upgrade copernicus-qa-tool/worker and copernicus-qa-tool/frontend services on the EEA Rancher platform

- In web browser, go to: [https://kvm-rancher-s3.eea.europa.eu/env/1a433/apps/stacks/1st203](https://kvm-rancher-s3.eea.europa.eu/env/1a433/apps/stacks/1st203)
- Login with your Eionet account
- Click the 'Upgrade' button on the worker and frontend lines, then edit the Image version (Select Image) and confirm with the 'Upgrade' button.
