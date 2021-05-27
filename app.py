import io
import logging
import os
import time

import boto3
import matplotlib.pyplot as plt
import pandas as pd
from botocore.exceptions import ClientError
from flask import Flask, render_template, request, jsonify, url_for, send_from_directory

from config import AWS_SESSION_TOKEN, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

emr_client = boto3.client('emr', region_name='us-east-1', aws_access_key_id=AWS_ACCESS_KEY_ID,
                          aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                          aws_session_token=AWS_SESSION_TOKEN)

s3_client = boto3.client('s3', region_name='us-east-1', aws_access_key_id=AWS_ACCESS_KEY_ID,
                         aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                         aws_session_token=AWS_SESSION_TOKEN)

s3_resource = boto3.resource("s3", region_name='us-east-1', aws_access_key_id=AWS_ACCESS_KEY_ID,
                             aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                             aws_session_token=AWS_SESSION_TOKEN)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = "uploaded_users_files"


def s3_upload(file_name, bucket, object_name=None):

    if object_name is None:
        object_name = file_name

    try:
        response = s3_client.upload_file(file_name, bucket, object_name)
    except ClientError as e:
        logging.error(e)
        return False
    return True


def s3_download(file_name, bucket, step):
    folders = s3_client.list_objects(Bucket="project-files-kpi", Prefix=f"output_folders/{step}")
    file = folders['Contents'][-1]["Key"].split("/")[-1]
    try:
        response = s3_client.download_file(bucket,
                                           f"output_folders/{step}/{file}",
                                           file_name)
    except ClientError as e:
        logging.error(e)
        return False
    return True


def add_emrfs_step(bucket_url, cluster_id, emr_client):
    job_flow_step = {
        'Name': 'Spark application',
        'ActionOnFailure': 'CONTINUE',
        'HadoopJarStep': {
            'Jar': 'command-runner.jar',
            'Args': [
                'spark-submit', '--deploy-mode', 'cluster', f'{bucket_url}/script/main.py', '--data_source',
                f'{bucket_url}/input_data/input.csv', '--output_uri',
                f'{bucket_url}/otput_data'
            ]
        }
    }

    try:
        response = emr_client.add_job_flow_steps(
            JobFlowId=cluster_id, Steps=[job_flow_step])
        step_id = response['StepIds'][0]
        print(f"Added step {step_id} to cluster {cluster_id}.")
    except ClientError:
        print(f"Couldn't add a step to cluster {cluster_id}.")
        raise
    else:
        return step_id


def usage_demo():
    cluster = emr_client.list_clusters(ClusterStates=['WAITING'])['Clusters'][0]
    add_emrfs_step(
        's3://project-files-kpi', cluster['Id'], emr_client)

    while True:
        clusters = emr_client.list_clusters(ClusterStates=['WAITING'])['Clusters']
        response = emr_client.list_steps(ClusterId=cluster['Id'], StepStates=['RUNNING', 'PENDING'])['Steps']
        if len(clusters) != 0 and len(response) == 0:
            break
        else:
            time.sleep(5)

    return emr_client.list_steps(ClusterId=cluster['Id'], StepStates=['COMPLETED'])['Steps'][0]['Id']


@app.route("/", methods=['GET', 'POST'])
def index():
    return render_template('index.html')


@app.route("/project", methods=['GET', 'POST'])
def project():
    if request.method == "GET":
        return render_template('project_status.html', status="Ready for work")
    else:
        file = request.files['file']
        # TODO check
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], file.filename))

        while True:
            if os.path.isfile(os.path.join(app.config['UPLOAD_FOLDER'], file.filename)):
                break
        s3_upload(f"uploaded_users_files/{file.filename}", "project-files-kpi", "input_data/input.csv")
        os.remove(f"uploaded_users_files/{file.filename}")
        return jsonify("EMR cluster is running. Please wait")


@app.route("/project_load_check", methods=['GET', 'POST'])
def project_load_check():
    step = usage_demo()

    files = list(s3_resource.Bucket("project-files-kpi").objects.filter(Prefix=f"otput_data/"))

    for i in files:
        i = i.key.split("/")[-1]

        copy_source = {
            'Bucket': 'project-files-kpi',
            'Key': f"otput_data/{i}"
        }
        s3_resource.meta.client.copy(copy_source, "project-files-kpi", f"output_folders/{step}/{i}")

        s3_resource.Object("project-files-kpi", f"otput_data/{i}").delete()
    return f"<a href='/results/{step}' class='form-link'>Follow the link to view the results</a>"


@app.route("/results", methods=['GET', 'POST'])
@app.route("/results/<step>", methods=['GET', 'POST'])
def results(step=None):
    if not step:
        folders = s3_client.list_objects(Bucket="project-files-kpi", Prefix=f"output_folders/", )['Contents']
        derecorys = []
        for folder in folders[1:]:
            fold = folder["Key"].replace(folders[0]["Key"], "").split("/")[0]
            if fold not in derecorys:
                derecorys.append(fold)
        return render_template('results.html', folders=derecorys, flag="1")
    else:
        folders = s3_client.list_objects(Bucket="project-files-kpi", Prefix=f"output_folders/{step}")
        file = folders['Contents'][1]["Key"].split("/")[-1]
        obj = s3_client.get_object(Bucket="project-files-kpi", Key=f"output_folders/{step}/{file}")
        df = pd.read_csv(io.BytesIO(obj['Body'].read()))

        plt.figure()

        df.plot(x='name', y=['hashtag_count'], kind='barh', figsize=(10, 15), title='Count hashtag in publication',
                fontsize=14)

        plt.xlabel('Count', fontsize=14)
        plt.ylabel("Hashtags", fontsize=14)

        plt.savefig('static/foo.png')

        return render_template('results.html', name=url_for("static", filename="foo.png"),
                               title=f"Top 30 most popular hashtags in step {step}", folders=step, flag="0")


@app.route("/download/<step>")
def download(step):
    s3_download("downloaded_users_files/res.csv", "project-files-kpi", step)
    return send_from_directory(directory="downloaded_users_files", path="res.csv")


if __name__ == "__main__":
    app.run(debug=True)
