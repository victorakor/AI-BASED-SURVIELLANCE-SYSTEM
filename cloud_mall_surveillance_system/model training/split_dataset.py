import os
import shutil
import random
from tqdm import tqdm # This line requires the 'tqdm' library to be installed

#ensure you have your dataset and are done with annotating the dataset with right labels

def split_dataset(base_dir, output_dir_path, train_ratio=0.8, val_ratio=0.1, test_ratio=0.1, random_seed=42):
    """
    Splits an image dataset with YOLO annotations into train, validation, and test sets.

    Args:
        base_dir (str): The path to the directory containing your category folders
                        (e.g., 'no_mask', 'medical_mask', 'other_coverings', 'weapons').
        output_dir_path (str): The absolute path where the processed dataset will be saved.
                               This directory will contain 'images' and 'labels' subfolders,
                               each with 'train', 'val', and 'test' splits.
        train_ratio (float): Proportion of data for the training set.
        val_ratio (float): Proportion of data for the validation set.
        test_ratio (float): Proportion of data for the test set.
        random_seed (int): Seed for reproducibility of the random split.
    """

    # Ensure ratios sum to 1
    if not (train_ratio + val_ratio + test_ratio == 1.0):
        print("Warning: Ratios do not sum to 1. Adjusting test_ratio.")
        test_ratio = 1.0 - train_ratio - val_ratio
        if test_ratio < 0:
            raise ValueError("Invalid ratios. train_ratio + val_ratio is greater than 1.0")

    random.seed(random_seed)

    # Define your class names and their corresponding integer IDs
    # IMPORTANT: The order here defines the class IDs (0, 1, 2, 3) in your YOLO labels.
    # Ensure this matches how you want them to be interpreted by the model.
    class_names = {
        "no_mask": 0,
        "medical_mask": 1,
        "other_coverings": 2,
        "weapons": 3
    }
    
    # Map for data.yaml
    yolo_class_names = [
        "no_mask",
        "mask",
        "other_coverings",
        "weapon"
    ]

    all_files = [] # List to hold (image_path, label_path, class_id) tuples

    print(f"Collecting files from: {base_dir}")
    for folder_name, class_id in class_names.items():
        folder_path = os.path.join(base_dir, folder_name)
        if not os.path.isdir(folder_path):
            print(f"Warning: Directory '{folder_path}' not found. Skipping.")
            continue

        print(f"Processing folder: {folder_name} (Class ID: {class_id})")
        images = [f for f in os.listdir(folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]

        for img_name in tqdm(images, desc=f"Collecting {folder_name} images"):
            img_path = os.path.join(folder_path, img_name)
            label_name = os.path.splitext(img_name)[0] + '.txt'
            label_path = os.path.join(folder_path, label_name)

            if os.path.exists(label_path):
                all_files.append((img_path, label_path, class_id))
            else:
                print(f"Warning: Annotation file not found for {img_name}. Skipping.")

    if not all_files:
        print("No image-label pairs found. Please check your base_dir and folder structure.")
        return

    random.shuffle(all_files) # Shuffle the combined list

    total_files = len(all_files)
    train_split = int(total_files * train_ratio)
    val_split = int(total_files * val_ratio)

    train_files = all_files[:train_split]
    val_files = all_files[train_split : train_split + val_split]
    test_files = all_files[train_split + val_split :]

    print(f"\nTotal files found: {total_files}")
    print(f"Train set size: {len(train_files)}")
    print(f"Validation set size: {len(val_files)}")
    print(f"Test set size: {len(test_files)}")

    # Create output directories
    output_images_dir = os.path.join(output_dir_path, "images")
    output_labels_dir = os.path.join(output_dir_path, "labels")

    for split_type in ["train", "val", "test"]:
        os.makedirs(os.path.join(output_images_dir, split_type), exist_ok=True)
        os.makedirs(os.path.join(output_labels_dir, split_type), exist_ok=True)

    # Function to copy files
    def copy_files(file_list, target_images_dir, target_labels_dir):
        for img_path, label_path, original_class_id in tqdm(file_list, desc="Copying files"):
            img_filename = os.path.basename(img_path)
            label_filename = os.path.basename(label_path)

            shutil.copy(img_path, os.path.join(target_images_dir, img_filename))
            
            # Read original label, replace class ID, and save to new location
            with open(label_path, 'r') as f_in:
                lines = f_in.readlines()
            
            new_lines = []
            for line in lines:
                parts = line.strip().split()
                if parts:
                    # The first part is the class ID. Replace it with the new class ID.
                    parts[0] = str(original_class_id) 
                    new_lines.append(" ".join(parts))
            
            with open(os.path.join(target_labels_dir, label_filename), 'w') as f_out:
                f_out.write("\n".join(new_lines))


    print("\nCopying training files...")
    copy_files(train_files, os.path.join(output_images_dir, "train"), os.path.join(output_labels_dir, "train"))

    print("Copying validation files...")
    copy_files(val_files, os.path.join(output_images_dir, "val"), os.path.join(output_labels_dir, "val"))

    print("Copying test files...")
    copy_files(test_files, os.path.join(output_images_dir, "test"), os.path.join(output_labels_dir, "test"))

    # Create data.yaml for YOLO training
    data_yaml_path = os.path.join(output_dir_path, "data.yaml")
    with open(data_yaml_path, 'w') as f:
        # The 'path' in data.yaml should be relative to where you run the YOLO train.py script.
        # If you place yolo_dataset inside 'faceMask_WeaponDetectionSystem',
        # and run train.py from 'faceMask_WeaponDetectionSystem', then 'path: ./yolo_dataset' is correct.
        # If you run train.py from 'ultralytics' folder, and 'faceMask_WeaponDetectionSystem' is a sibling,
        # then 'path: ../faceMask_WeaponDetectionSystem/yolo_dataset' would be needed.
        # For simplicity, let's assume you'll run train.py from 'faceMask_WeaponDetectionSystem'
        # or adjust the path in data.yaml manually later if needed.
        f.write(f"path: {os.path.basename(output_dir_path)}\n") # This will be 'yolo_dataset'
        f.write("train: images/train\n")
        f.write("val: images/val\n")
        f.write("test: images/test\n\n") # Optional, but good practice

        f.write(f"nc: {len(yolo_class_names)}\n")
        f.write("names:\n")
        for i, name in enumerate(yolo_class_names):
            f.write(f"  {i}: {name}\n")

    print(f"\nDataset split and organized successfully in '{output_dir_path}'!")
    print(f"A 'data.yaml' file has been created at '{data_yaml_path}' for YOLO training configuration.")
    print("Next, we'll move on to Model Selection and Training!")

if __name__ == "__main__":
    # --- IMPORTANT: Configure these paths ---
    # Path to the directory containing your 'no_mask', 'medical_mask', 'other_coverings', and 'weapons' folders.
    base_directory = r"C:\Users\hp\.vscode\FinalProjectFolder\faceMask_WeaponDetectionSystem\datasets"

    # The desired absolute path for the output 'yolo_dataset' folder.
    # This will create 'yolo_dataset' directly inside 'faceMask_WeaponDetectionSystem'.
    output_dataset_path = r"C:\Users\hp\.vscode\FinalProjectFolder\faceMask_WeaponDetectionSystem\yolo_dataset"

    split_dataset(base_directory, output_dataset_path)