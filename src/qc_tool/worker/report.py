

import json
from datetime import datetime
from os.path import normpath
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate
from reportlab.platypus import Frame
from reportlab.platypus import Image
from reportlab.platypus import PageTemplate
from reportlab.platypus import Paragraph
from reportlab.platypus import Table
from reportlab.platypus import TableStyle

from qc_tool.common import compile_job_report_data
from qc_tool.common import JOB_ERROR
from qc_tool.common import JOB_FAILED
from qc_tool.common import JOB_OK
from qc_tool.common import JOB_PARTIAL
from qc_tool.common import QCException
from qc_tool.common import TIME_FORMAT
from qc_tool.common import CONFIG


def generate_pdf_report(job_report_filepath, job_uuid):
    job_report = compile_job_report_data(job_uuid)

    # Set report title
    report_title = "QC tool check report"

    # set report page size to A4
    doc = BaseDocTemplate(str(job_report_filepath), pagesize=A4)
    doc.title = report_title

    # Set custom styles
    styles = getSampleStyleSheet()
    style_body = styles["BodyText"]
    style_normal = styles["Normal"]
    style_check_default = ParagraphStyle("status_other", parent=style_normal)
    style_check_ok = ParagraphStyle("status_ok", parent=style_normal, textColor=colors.green)
    style_check_failed = ParagraphStyle("status_failed", parent=style_normal, textColor=colors.red)
    style_check_partial = ParagraphStyle("status_partial", parent=style_normal, textColor=colors.orange)

    # Create page footer.
    def footer(canvas, doc):
        canvas.saveState()
        styles = getSampleStyleSheet()
        style_normal = styles["Normal"]
        p = Paragraph("{:s} - {:s}  ".format(report_title, job_report["filename"]), style_normal)
        w, h = p.wrap(doc.width, doc.bottomMargin)
        p.drawOn(canvas, doc.leftMargin, h)
        canvas.restoreState()

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="frame_normal")
    template = PageTemplate(id="report_page_template", frames=frame, onPage=footer)
    doc.addPageTemplates([template])

    # Setup main document object.
    text = []

    # Add logo images. The three logos are placed inside an invisible table.
    report_logo_dirpath = Path(normpath(str(Path(__file__).joinpath("../report_images"))))
    with open(str(report_logo_dirpath.joinpath("copernicus_logo_resized.png")), "rb") as copernicus_f, \
        open(str(report_logo_dirpath.joinpath("eea_full_logo_resized.png")), "rb") as eea_f, \
        open(str(report_logo_dirpath.joinpath("land_monitoring_logo_resized.png")), "rb") as land_f:

        if CONFIG["show_logo"]:
            copernicus_image = Image(copernicus_f, width=123, height=53)
            eea_image = Image(eea_f, width=178, height=38)
            land_image = Image(land_f, width=124, height=57)
            image_data = [[copernicus_image, land_image, eea_image]]
            image_table=Table(image_data, hAlign="CENTER", colWidths=[130, 150, 200], rowHeights=60)
            image_table_style = TableStyle([("VALIGN", (0, 0), (-1,-1), "CENTER")])
            image_table.setStyle(image_table_style)
            text.append(image_table)
            text.append(Paragraph("", style_normal))

        # Add main heading
        text.append(Paragraph(report_title, styles["Heading1"]))

        # Add summary table
        text.append(Paragraph("", styles["Heading1"]))
        text.append(Paragraph("Report summary", styles["Heading2"]))
        status_file = ["File name", job_report["filename"]]
        status_product = ["Product", job_report["description"]]
        display_date = datetime.strptime(job_report["job_finish_date"], TIME_FORMAT).strftime("%Y-%m-%d %H:%M:%S")
        status_date = ["Checked on", display_date]
        job_status = job_report["status"]
        if job_status is None:
            job_status = JOB_ERROR
        if job_status in (JOB_ERROR, JOB_FAILED):
            job_status_style = style_check_failed
        elif job_status == JOB_OK:
            job_status_style = style_check_ok
        elif job_status == JOB_PARTIAL:
            job_status_style = style_check_partial
        else:
            raise QCException("Unknown job status {:s}.".format(repr(job_status)))

        # Retrieve QC tool version
        qc_tool_version = ["QC tool version", job_report.get("qc_tool_version", "Not Available")]

        # Compile summary table
        job_status = ["Job status", Paragraph(job_status, job_status_style)]
        summary_data = [status_file, status_product, status_date, qc_tool_version, job_status]
        summary_table = Table(summary_data, hAlign="LEFT", colWidths=[90, None])
        summary_style = TableStyle([("INNERGRID", (0, 0), (-1, -1), 0.25, colors.black),
                                    ("BOX", (0, 0), (-1, -1), 0.25, colors.black),
                                    ("VALIGN", (0, 0), (-1,-1), "TOP")])
        summary_table.setStyle(summary_style)
        text.append(summary_table)

        # Detail table title
        text.append(Paragraph("", style_normal))
        text.append(Paragraph("", style_normal))
        text.append(Paragraph("Report details", styles["Heading2"]))

        # Detail table header row
        check_table_header = [Paragraph("<b>CHECK</b>", style_normal),
                              Paragraph("<b>LAYERS</b>", style_normal),
                              Paragraph("<b>STATUS</b>", style_normal),
                              Paragraph("<b>MESSAGES</b>", style_normal)]
        check_data = [check_table_header]

        # Detail table data. Text color is displayed based on check status.
        for step_report in job_report["steps"]:
            step_status = step_report["status"]
            step_layers = step_report["layers"]
            step_ident = step_report["check_ident"]

            if step_ident.startswith("qc_tool."):
                step_ident = ".".join(step_ident.split(".")[1:])

            if step_layers is None:
                step_layers = []

            if step_status is None:
                step_status = "not run"
            if step_status == "ok":
                display_ident = [Paragraph("<i>" + step_ident + "</i>", style_check_default),
                                 Paragraph(step_report["description"], style_check_default)]
                display_layers = [Paragraph(step_layer, style_check_default) for step_layer in step_layers]
                display_status = Paragraph("<b>" + step_status + "</b>", style_check_ok)
            elif step_status in ["aborted", "failed", "error"]:
                display_ident = [Paragraph("<i>" + step_ident + "</i>", style_check_failed),
                                 Paragraph(step_report["description"], style_check_failed)]
                display_layers = [Paragraph(step_layer, style_check_failed) for step_layer in step_layers]
                display_status = Paragraph(step_status, style_check_failed)
            else:
                display_ident = [Paragraph("<i>" + step_ident + "</i>", style_check_default),
                                 Paragraph(step_report["description"], style_check_default)]
                display_layers = [Paragraph(step_layer, style_check_default) for step_layer in step_layers]
                display_status = Paragraph(step_status, style_check_default)

            messages = step_report.get("messages", [])
            if messages is None:
                messages = []
            display_messages = []
            for message in messages:
                display_messages.append(Paragraph(message, style_body))

            check_info = [display_ident,
                          display_layers,
                          display_status,
                          display_messages
                          ]
            check_data.append(check_info)

        detail_table=Table(check_data, hAlign="LEFT", colWidths=[None, 60, 60, None])
        detail_table_style = TableStyle([("INNERGRID", (0, 0), (-1, -1), 0.25, colors.black),
                                         ("BOX", (0, 0), (-1, -1), 0.25, colors.black),
                                         ("VALIGN", (0, 0), (-1,-1), "TOP")])
        detail_table.setStyle(detail_table_style)
        text.append(detail_table)

        text.append(Paragraph("", style_normal))
        text.append(Paragraph("", style_normal))
        text.append(Paragraph("", style_normal))

        doc.build(text)
