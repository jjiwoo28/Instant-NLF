import os
import glob
import numpy as np
import math
import json
import trimesh
import argparse

# returns point closest to both rays of form o+t*d, and a weight factor that goes to 0 if the lines are parallel
def closest_point_2_lines(oa, da, ob, db): 
    da = da / np.linalg.norm(da)
    db = db / np.linalg.norm(db)
    c = np.cross(da, db)
    denom = np.linalg.norm(c)**2
    t = ob - oa
    ta = np.linalg.det([t, db, c]) / (denom + 1e-10)
    tb = np.linalg.det([t, da, c]) / (denom + 1e-10)
    if ta > 0:
        ta = 0
    if tb > 0:
        tb = 0
    return (oa+ta*da+ob+tb*db) * 0.5, denom

def rotmat(a, b):
	a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
	v = np.cross(a, b)
	c = np.dot(a, b)
	# handle exception for the opposite direction input
	if c < -1 + 1e-10:
		return rotmat(a + np.random.uniform(-1e-2, 1e-2, 3), b)
	s = np.linalg.norm(v)
	kmat = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
	return np.eye(3) + kmat + kmat.dot(kmat) * ((1 - c) / (s ** 2 + 1e-10))


def visualize_poses(poses, size=0.1):
    # poses: [B, 4, 4]

    axes = trimesh.creation.axis(axis_length=4)
    box = trimesh.primitives.Box(extents=(2, 2, 2)).as_outline()
    box.colors = np.array([[128, 128, 128]] * len(box.entities))
    objects = [axes, box]

    for pose in poses:
        # a camera is visualized with 8 line segments.
        pos = pose[:3, 3]
        a = pos + size * pose[:3, 0] + size * pose[:3, 1] + size * pose[:3, 2]
        b = pos - size * pose[:3, 0] + size * pose[:3, 1] + size * pose[:3, 2]
        c = pos - size * pose[:3, 0] - size * pose[:3, 1] + size * pose[:3, 2]
        d = pos + size * pose[:3, 0] - size * pose[:3, 1] + size * pose[:3, 2]

        dir = (a + b + c + d) / 4 - pos
        dir = dir / (np.linalg.norm(dir) + 1e-8)
        o = pos + dir * 3

        segs = np.array([[pos, a], [pos, b], [pos, c], [pos, d], [a, b], [b, c], [c, d], [d, a], [pos, o]])
        segs = trimesh.load_path(segs)
        objects.append(segs)

    trimesh.Scene(objects).show()

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('path', type=str, help="root directory to the LLFF dataset (contains images/ and pose_bounds.npy)")
    parser.add_argument('--images', type=str, default='images_8', help="images folder (do not include full path, e.g., just use `images_4`)")
    parser.add_argument('--downscale', type=float, default=8, help="image size down scale, e.g., 4")
    parser.add_argument('--hold', type=int, default=8, help="hold out for validation every $ images")

    opt = parser.parse_args()
    print(f'[INFO] process {opt.path}')

    # path must end with / to make sure image path is relative
    if opt.path[-1] != '/':
        opt.path += '/'
    
    # load data
    images = [f[len(opt.path):] for f in sorted(glob.glob(os.path.join(opt.path, opt.images, "*"))) if f.lower().endswith('png') or f.lower().endswith('jpg') or f.lower().endswith('jpeg')]
    
    poses_bounds = np.load(os.path.join(opt.path, 'poses_bounds.npy'))
    N = poses_bounds.shape[0]

    print(f'[INFO] loaded {len(images)} images, {N} poses_bounds as {poses_bounds.shape}')

    assert N == len(images)

    poses = poses_bounds[:, :15].reshape(-1, 3, 5) # (N, 3, 5)
    bounds = poses_bounds[:, -2:] # (N, 2)

    close_depth, inf_depth = bounds.min()*.9, bounds.max()*5.
    dt = .75
    mean_dz = 1./(((1.-dt)/close_depth + dt/inf_depth))
    focal_depth = mean_dz
    
    H, W, fl = poses[0, :, -1] 

    H = H // opt.downscale
    W = W // opt.downscale
    fl = fl / opt.downscale

    print(f'[INFO] H = {H}, W = {W}, fl = {fl} focal_depth = {focal_depth} (downscale = {opt.downscale})')

    # inversion of this: https://github.com/Fyusion/LLFF/blob/c6e27b1ee59cb18f054ccb0f87a90214dbe70482/llff/poses/pose_utils.py#L51
    poses = np.concatenate([poses[..., 1:2], poses[..., 0:1], -poses[..., 2:3], poses[..., 3:4]], -1) # (N, 3, 4)

    # to homogeneous 
    last_row = np.tile(np.array([0, 0, 0, 1]), (len(poses), 1, 1)) # (N, 1, 4)
    poses = np.concatenate([poses, last_row], axis=1) # (N, 4, 4) 

    # visualize_poses(poses)

    # the following stuff are from colmap2nerf... [flower fails, the camera must be in-ward...]
    # poses[:, 0:3, 1] *= -1
    # poses[:, 0:3, 2] *= -1
    # poses = poses[:, [1, 0, 2, 3], :] # swap y and z
    # poses[:, 2, :] *= -1 # flip whole world upside down

    # up = poses[:, 0:3, 1].sum(0)
    # up = up / np.linalg.norm(up)
    # R = rotmat(up, [0, 0, 1]) # rotate up vector to [0,0,1]
    # R = np.pad(R, [0, 1])
    # R[-1, -1] = 1

    # poses = R @ poses

    # totw = 0.0
    # totp = np.array([0.0, 0.0, 0.0])
    # for i in range(N):
    #     mf = poses[i, :3, :]
    #     for j in range(i + 1, N):
    #         mg = poses[j, :3, :]
    #         p, w = closest_point_2_lines(mf[:,3], mf[:,2], mg[:,3], mg[:,2])
    #         #print(i, j, p, w)
    #         if w > 0.01:
    #             totp += p * w
    #             totw += w
    # totp /= totw
    # print(f'[INFO] totp = {totp}')
    # poses[:, :3, 3] -= totp
    # avglen = np.linalg.norm(poses[:, :3, 3], axis=-1).mean()
    # poses[:, :3, 3] *= 4.0 / avglen
    # print(f'[INFO] average radius = {avglen}')

#jw
    positions = poses[:, :3, 3]

    # 최대 및 최소 값 계산
    max_pos = positions.max(axis=0)
    min_pos = positions.min(axis=0)

    # 분모가 0이 되는 것을 방지
    scale = max_pos - min_pos
    scale[scale == 0] = 1  # 0인 경우 1로 설정하여 나눗셈에서 0으로 나누는 것을 방지

    # 각 축별로 정규화 수행
    normalized_positions = 2 * (positions - min_pos) / scale - 1

    # 정규화된 위치 벡터를 원래의 포즈에 다시 할당
    poses[:, :3, 3] = normalized_positions
#jw


    # visualize_poses(poses)

    # construct frames

    all_ids = np.arange(N)
    test_ids = all_ids[::opt.hold]
    train_ids = np.array([i for i in all_ids])

    frames_train = []
    frames_test = []
    for i in train_ids:
        frames_train.append({
            'file_path': images[i],
            'transform_matrix': poses[i].tolist(),
        })
    for i in test_ids:
        frames_test.append({
            'file_path': images[i],
            'transform_matrix': poses[i].tolist(),
        })

    def write_json(filename, frames):

        # construct a transforms.json
        out = {
            'w': W,
            'h': H,
            'fl_x': fl,
            'fl_y': fl,
            'cx': W // 2,
            'cy': H // 2,
            'aabb_scale': 2,
            'frames': frames,
            'focal_depth':focal_depth,
        }

        # write
        output_path = os.path.join(opt.path, filename)
        print(f'[INFO] write {len(frames)} images to {output_path}')
        with open(output_path, 'w') as f:
            json.dump(out, f, indent=2)

    write_json('transforms_train.json', frames_train)
    write_json('transforms_val.json', frames_test[::10])
    write_json('transforms_test.json', frames_test)

    def read_json_to_dict(filename):
        input_path = os.path.join(opt.path, filename)
        if os.path.exists(input_path):
            with open(input_path, 'r') as f:
                data = json.load(f)
                print(f'[INFO] {filename} 내용:')
                print(json.dumps(data, indent=2))
                return data
        else:
            print(f'[ERROR] 파일을 찾을 수 없습니다: {input_path}')
            return None

    # 저장된 JSON 파일들 다시 읽기 및 딕셔너리로 저장
    transforms_train_dict = read_json_to_dict('transforms_train.json')
    transforms_val_dict = read_json_to_dict('transforms_val.json')
    transforms_test_dict = read_json_to_dict('transforms_test.json')

    temp = []
    for i in range(len(transforms_train_dict['frames'])):
        temp.append(transforms_train_dict['frames'][i]['transform_matrix'])

    temp = np.array(temp)

    print("test")


