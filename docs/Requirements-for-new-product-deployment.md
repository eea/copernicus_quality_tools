To ensure a smooth validation of a product, the QC Tool must first be configured. The preparatory work consists of setting up the QC workflow (JSON recipes), ensuring that all required test routines are present and functional, and verifying that the tool is ready to handle the defined product specifications and expected data volumes. The requirements outlined below provide the technical, logistical, and validation context necessary for configuring the QC Tool, implementing the product-specific checks, and integrating the product into the operational workflow.

Requirements for New Product Deployment in the CLMS QC Tool:

**Lead Time for Deployment**
* A formal request for deployment must be submitted at least 3 months in advance. This lead time ensures the development team can prepare the tool accordingly and ensure smooth operations.

**Tool Interaction Details** 
* QC Tool instance: Specify if you intend to use an EEA-hosted instance or a self-deployed instance. Which option to choose depends on the product type and must be agreed with the responsible EEA PO.
* Deployment capacity: If self-deployed, specify the expected data volumes and the number of files to be checked. This information will help us configure the tool appropriately and support you with scaling.
* Delivery method: Clarify whether deliveries will be provided as ZIP archives uploaded to the system or as registered S3 deliveries.
* Interface preference: State whether the QC Tool will be accessed primarily via the user interface (UI) or through the application programming interface (API).

**Technical Specification of the Product**

In many cases, the request is about a product update. In such cases, an existing workflow can be reused and adapted to the new specifications. The QC Tool already covers most of the required checks, but it may eventually need to be expanded to include additional capabilities.
* Product User Manual (PUM): The PUM should include all essential technical details about the product, such as the file naming convention, versioning scheme, and mapping rules. 
* Layer definition: Submit a full list of product layers, clearly marking each as vector or raster.
* Delivery units:
    * If using an existing grid system (e.g. EEA38 100m or EEA39 100m grid), specify this explicitly.
    * If introducing a new grid or boundary system, a boundary package dataset must be provided.
* Specify the required checks by selecting from the available [[Vector checks]] and [[Raster checks]]. If a test is missing, please inform us so it can be added.

**Provision of Testing Data**

* Sample datasets: Provide at least three representative samples for each layer subject to quality checks.
* S3 deliveries: If the product is delivered via S3, supply the necessary credentials for accessing the bucket with sample data.
* Parallel runs: For tiled S3 deliveries configured for multiple parallel runs, ensure the dataset is at least 3 × n samples, where n is the number of parallel runs.
* MMU validation: If a Minimum Mapping Unit (MMU) check applies, the sample dataset must include at least one cluster of 9 neighbouring delivery units for robust validation.

By following these requirements, requesters can help ensure that their products are validated efficiently, that quality checks are applied consistently, and that integration into the Copernicus Land Monitoring workflows proceeds without delays.
