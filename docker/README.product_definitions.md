# Editing Product Definitions

When deployed, the QC tool uses product definition .json files located inside its docker containers.
The product definition files are cloned from the GitHub master branch every time a docker container is rebuilt.
Local edits to a product definition file do not have any effect on the product definition file used by the QC tool.

If you want to use a custom product definition .json file in the QC tool, you will need to adjust your *docker-compose yml* file to use a bind mount.
Open **docker-compose.service_provider.yml** in a text editor and change the **volumes** sections of **qc_tool_frontend** and **qc_tool_wps**:

In **qc_tool_frontend** change:
<pre>
volumes:
      - qc_tool_volume:/mnt/qc_tool_volume
      - qc_tool_frontend:/var/lib/qc_tool
</pre>
to:
<pre>
volumes:
      - qc_tool_volume:/mnt/qc_tool_volume
      - qc_tool_frontend:/var/lib/qc_tool
      - ../../copernicus_quality_tools:/usr/local/src/copernicus_quality_tools
</pre>

In **qc_tool_wps** change:
<pre>
volumes:
      - qc_tool_volume:/mnt/qc_tool_volume
</pre>
to:
<pre>
volumes:
      - qc_tool_volume:/mnt/qc_tool_volume
      - ../../copernicus_quality_tools:/usr/local/src/copernicus_quality_tools
</pre>

The new entries in the volumes sections have two paths separated by a colon character:
* The first part *../../copernicus_quality_tools* means 'path to the source code directory from **host point of view**' _(relative to the docker-compose yml file)_
* The second part */usr/local/src/copernicus_quality_tools* means 'path to the source code directory from **container point of view**'

Please see an example docker-compose file here: https://github.com/eea/copernicus_quality_tools/blob/master/docker/docker-compose.editable_product.yml
Once you edit your docker-compose.service_provider.yml and restart (docker-compose -f ./docker-compose.service_provider.yml -p qc_tool_app up), you should be able to see your custom product definition in the web application.

