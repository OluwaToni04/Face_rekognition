import boto3  # AWS SDK for Python

# Create S3 resource object (used to interact with S3)
s3 = boto3.resource("s3")

# 🔹 Your S3 bucket name (must match exactly)
BUCKET_NAME = "facesof-people"

# 🔹 List of images and their labels (name you want to store)
# Each tuple = (image file, person/label name)
images = [
    ("image1.jpg", "Tyla Laura"),
    ("image2.jpg", "Tyla Laura"),
    ("image3.jpg", "Tyla Laura"),
    ("image4.jpg", "Olivia Dean"),
    ("image5.jpg", "Olivia Dean"),
    ("image6.jpg", "Olivia Dean"),
    ("image7.jpg", "Ariana Grande"),
    ("image8.jpg", "Ariana Grande"),
    ("image9.jpg", "Ariana Grande"),
]

# 🔁 Loop through each image and upload to S3
for image_file, label in images:

    # 🔹 Open image file in binary mode (required for upload)
    with open(image_file, "rb") as file:

        # 🔹 Create S3 object path
        # Example result: index/image1.jpg
        obj = s3.Object(BUCKET_NAME, "index/" + image_file)

        # 🔹 Upload file to S3
        obj.put(
            Body=file,

            # 🔹 Metadata attached to the file
            # VERY IMPORTANT: keys must be lowercase
            # Lambda will read this later
            Metadata={
                "fullname": label
            },

            # 🔹 Content type (helps S3 understand file type)
            ContentType="image/jpeg"
        )

    # 🔹 Print confirmation for each upload
    print(f"Uploaded {image_file} for {label}")