import os
import uuid
import base64
import io
from datetime import datetime

import boto3
from botocore.exceptions import ClientError
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Load configuration from environment variables
AWS_REGION = os.getenv("AWS_REGION", "eu-west-1")
S3_BUCKET = os.getenv("S3_BUCKET", "facesof-people")
COLLECTION_ID = os.getenv("COLLECTION_ID", "facerekogn")
DYNAMODB_TABLE = os.getenv("DYNAMODB_TABLE", "face_recognition")

# Confidence threshold for identity verification
CONFIDENCE_THRESHOLD = 80.0

# Initialize AWS clients
s3 = boto3.client("s3", region_name=AWS_REGION)
rekognition = boto3.client("rekognition", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)

# Reference DynamoDB table
table = dynamodb.Table(DYNAMODB_TABLE)


# Helper Function: Upload file to S3
def upload_file_to_s3(file_obj, filename, metadata=None, folder="uploads"):
    """
    Uploads a file to S3 with optional metadata.

    Args:
        file_obj: File object from request
        filename: Original file name
        metadata: Dictionary of metadata (e.g., fullname)
        folder: S3 folder (e.g., registered, search)

    Returns:
        s3_key: Path of uploaded file in S3
    """
    s3_key = f"{folder}/{uuid.uuid4()}_{filename}"

    extra_args = {
        "ContentType": getattr(file_obj, "content_type", None) or "image/jpeg"
    }

    if metadata:
        extra_args["Metadata"] = metadata

    s3.upload_fileobj(file_obj, S3_BUCKET, s3_key, ExtraArgs=extra_args)
    return s3_key


# Route: Home
@app.route("/", methods=["GET"])
def home():
    """Basic route to check if API is running"""
    return jsonify({
        "message": "Face Recognition API is running"
    })


# Route: Register Face
@app.route("/register", methods=["POST"])
def register_face():
    """
    Registers a new face:
    1. Upload image to S3
    2. Index face into Rekognition collection
    3. Store face details in DynamoDB
    """
    try:
        if "image" not in request.files:
            return jsonify({"error": "Image file is required"}), 400

        full_name = request.form.get("full_name")
        if not full_name:
            return jsonify({"error": "full_name is required"}), 400

        image = request.files["image"]
        metadata = {"fullname": full_name}

        s3_key = upload_file_to_s3(
            image,
            image.filename,
            metadata=metadata,
            folder="registered"
        )

        response = rekognition.index_faces(
            CollectionId=COLLECTION_ID,
            Image={
                "S3Object": {
                    "Bucket": S3_BUCKET,
                    "Name": s3_key
                }
            },
            DetectionAttributes=[]
        )

        face_records = response.get("FaceRecords", [])

        if not face_records:
            return jsonify({
                "error": "No face detected in the uploaded image"
            }), 400

        face_id = face_records[0]["Face"]["FaceId"]

        table.put_item(
            Item={
                "RekognitionId": face_id,
                "FullName": full_name,
                "Bucket": S3_BUCKET,
                "ImageKey": s3_key,
                "CreatedAt": datetime.utcnow().isoformat()
            }
        )

        return jsonify({
            "message": "Face registered successfully",
            "FaceId": face_id,
            "FullName": full_name,
            "ImageKey": s3_key
        }), 201

    except ClientError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Route: Recognize Face
@app.route("/recognize", methods=["POST"])
def recognize_face():
    """
    Recognizes a face:
    1. Upload image to S3
    2. Search face in Rekognition collection
    3. Fetch matching person from DynamoDB
    """
    try:
        if "image" not in request.files:
            return jsonify({"error": "Image file is required"}), 400

        image = request.files["image"]

        s3_key = upload_file_to_s3(
            image,
            image.filename,
            folder="search"
        )

        response = rekognition.search_faces_by_image(
            CollectionId=COLLECTION_ID,
            Image={
                "S3Object": {
                    "Bucket": S3_BUCKET,
                    "Name": s3_key
                }
            },
            MaxFaces=1,
            FaceMatchThreshold=80
        )

        matches = response.get("FaceMatches", [])

        if not matches:
            return jsonify({
                "message": "No match found",
                "ImageKey": s3_key
            }), 404

        best_match = matches[0]
        face_id = best_match["Face"]["FaceId"]
        similarity = best_match["Similarity"]

        result = table.get_item(Key={"RekognitionId": face_id})
        item = result.get("Item")

        if not item:
            return jsonify({
                "message": "Face matched but not found in database",
                "FaceId": face_id,
                "Similarity": similarity
            }), 404

        return jsonify({
            "message": "Match found",
            "FaceId": face_id,
            "Similarity": similarity,
            "FullName": item.get("FullName"),
            "Bucket": item.get("Bucket"),
            "ImageKey": item.get("ImageKey"),
            "SearchImageKey": s3_key
        }), 200

    except ClientError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Route: Submit Insurance Claim with Identity Verification
@app.route("/submit-claim", methods=["POST"])
def submit_claim():
    """
    Insurance Identity Verification endpoint.

    Accepts a policy_id and a base64-encoded selfie image,
    verifies the claimant's identity against the registered
    policyholder face on file, and returns a fraud risk assessment.

    Request JSON:
        {
            "policy_id": "string",        -- RekognitionId of registered policyholder
            "selfie_image": "string"      -- base64-encoded JPEG/PNG image
        }

    Response JSON:
        {
            "verified": bool,
            "confidence_score": float,
            "risk_flag": bool,
            "message": string
        }
    """
    try:
        data = request.get_json()

        # --- Validate inputs ---
        if not data:
            return jsonify({"error": "JSON body is required"}), 400

        policy_id = data.get("policy_id")
        selfie_b64 = data.get("selfie_image")

        if not policy_id:
            return jsonify({"error": "policy_id is required"}), 400

        if not selfie_b64:
            return jsonify({"error": "selfie_image is required"}), 400

        # --- Look up policyholder in DynamoDB ---
        result = table.get_item(Key={"RekognitionId": policy_id})
        policyholder = result.get("Item")

        if not policyholder:
            return jsonify({
                "error": "Policy ID not found. No registered policyholder matches this ID."
            }), 404

        # --- Fetch reference image from S3 ---
        reference_image_key = policyholder.get("ImageKey")

        if not reference_image_key:
            return jsonify({
                "error": "No reference image found for this policy ID."
            }), 404

        try:
            s3_response = s3.get_object(Bucket=S3_BUCKET, Key=reference_image_key)
            reference_image_bytes = s3_response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return jsonify({
                    "error": "Reference image no longer exists in storage."
                }), 404
            raise

        # --- Decode the selfie from base64 ---
        try:
            # Strip data URI prefix if present (e.g. "data:image/jpeg;base64,")
            if "," in selfie_b64:
                selfie_b64 = selfie_b64.split(",", 1)[1]
            selfie_bytes = base64.b64decode(selfie_b64)
        except Exception:
            return jsonify({"error": "selfie_image is not valid base64."}), 400

        # --- Compare faces using Rekognition ---
        try:
            compare_response = rekognition.compare_faces(
                SourceImage={"Bytes": reference_image_bytes},
                TargetImage={"Bytes": selfie_bytes},
                SimilarityThreshold=0  # fetch all results; we apply our own threshold
            )
        except rekognition.exceptions.InvalidParameterException:
            return jsonify({
                "verified": False,
                "confidence_score": 0.0,
                "risk_flag": True,
                "message": "No face detected in the submitted selfie. Claim flagged for manual review."
            }), 200
        except ClientError as e:
            return jsonify({"error": f"Rekognition error: {str(e)}"}), 500

        face_matches = compare_response.get("FaceMatches", [])

        # --- Evaluate match ---
        if not face_matches:
            return jsonify({
                "verified": False,
                "confidence_score": 0.0,
                "risk_flag": True,
                "message": "Identity could not be verified. No facial match found. Claim flagged for manual review."
            }), 200

        confidence = face_matches[0]["Similarity"]
        verified = confidence >= CONFIDENCE_THRESHOLD
        risk_flag = not verified

        if verified:
            message = (
                f"Identity verified successfully. "
                f"Claimant matches policyholder '{policyholder.get('FullName')}' "
                f"with {confidence:.1f}% confidence."
            )
        else:
            message = (
                f"Identity verification failed. Confidence score {confidence:.1f}% "
                f"is below the required {CONFIDENCE_THRESHOLD}% threshold. "
                f"Claim flagged for manual review."
            )

        return jsonify({
            "verified": verified,
            "confidence_score": round(confidence, 2),
            "risk_flag": risk_flag,
            "message": message
        }), 200

    except ClientError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Run Flask App
if __name__ == "__main__":
    app.run(debug=True)