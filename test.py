import boto3
from botocore.exceptions import ClientError

# AWS clients
s3 = boto3.client("s3", region_name="eu-west-1")
rekognition = boto3.client("rekognition", region_name="eu-west-1")
dynamodb = boto3.resource("dynamodb", region_name="eu-west-1")

# Project settings
BUCKET_NAME = "facesof-people"
COLLECTION_ID = "facerekogn"
TABLE_NAME = "face_recognition"

# Local image to test
LOCAL_IMAGE_PATH = "test.jpg"

# S3 key for the test image
S3_TEST_KEY = "search/test.jpg"

table = dynamodb.Table(TABLE_NAME)


def upload_test_image():
    """Upload the local test image to S3."""
    try:
        with open(LOCAL_IMAGE_PATH, "rb") as file:
            s3.upload_fileobj(file, BUCKET_NAME, S3_TEST_KEY)
        print(f"Uploaded {LOCAL_IMAGE_PATH} to s3://{BUCKET_NAME}/{S3_TEST_KEY}")
    except FileNotFoundError:
        print(f"File not found: {LOCAL_IMAGE_PATH}")
        return False
    except ClientError as e:
        print("S3 upload error:", e)
        return False

    return True


def recognize_face():
    """Search for the face in the Rekognition collection."""
    try:
        response = rekognition.search_faces_by_image(
            CollectionId=COLLECTION_ID,
            Image={
                "S3Object": {
                    "Bucket": BUCKET_NAME,
                    "Name": S3_TEST_KEY
                }
            },
            MaxFaces=1,
            FaceMatchThreshold=80
        )

        matches = response.get("FaceMatches", [])

        if not matches:
            print("No match found.")
            return None

        match = matches[0]
        face_id = match["Face"]["FaceId"]
        similarity = match["Similarity"]

        print(f"Match found. FaceId: {face_id}")
        print(f"Similarity: {similarity:.2f}%")

        return face_id

    except ClientError as e:
        print("Rekognition error:", e)
        return None


def get_person_from_dynamodb(face_id):
    """Get the matched person's details from DynamoDB."""
    try:
        response = table.get_item(Key={"RekognitionId": face_id})

        item = response.get("Item")
        if not item:
            print("Face found in Rekognition, but not in DynamoDB.")
            return

        print("\nPerson found in database:")
        print("FullName:", item.get("FullName", "N/A"))
        print("Bucket:", item.get("Bucket", "N/A"))
        print("ImageKey:", item.get("ImageKey", "N/A"))

    except ClientError as e:
        print("DynamoDB error:", e)


def main():
    print("Testing face recognition project...\n")

    uploaded = upload_test_image()
    if not uploaded:
        return

    face_id = recognize_face()
    if not face_id:
        return

    get_person_from_dynamodb(face_id)


if __name__ == "__main__":
    main()