import cv2
import numpy as np
import requests
from abc import ABCMeta, abstractmethod
from multiprocessing import Pool
from threading import Thread


class DataLoader(metaclass=ABCMeta):
    def __init__(self):
        self.__after_load_callback = None

    def load(self, data: {}):
        """
        Load image
        :param data:
        :return: image object
        """
        self._load(data)
        if self.__after_load_callback is not None:
            self.__after_load_callback(data)
        return data

    def after_load(self, callback: callable):
        """
        Set operations, that performs after every loading
        :param callback: callback function that will be called
        :return:
        """
        self.__after_load_callback = callback
        return self

    @abstractmethod
    def _load(self, data: {}):
        """
        Load image
        :param path: path to image
        :return: image object
        """


class PathLoader(DataLoader):
    def _load(self, data: {}):
        try:
            data['object'] = cv2.imread(data['path'], cv2.IMREAD_COLOR)
        except:
            data['object'] = None
        return data


class UrlLoader(DataLoader):
    def _load(self, data: {}):
        try:
            response = requests.get(data['path'], timeout=100)
            if response.ok:
                data_array = np.asarray(bytearray(response.content), dtype=np.uint8)
                data['object'] = cv2.imdecode(data_array, cv2.IMREAD_COLOR)
            else:
                data['object'] = None
        except:
            data['object'] = None

        return data


def load_image(info: [DataLoader, {}]):
    return info[0].load(info[1])


class DataConveyor:
    def __init__(self, image_loader: DataLoader, pathes: [{}] = None, batch_size: int = 1,
                 get_images_num: int = None):
        self.__batch_size = batch_size
        self.__image_pathes = pathes
        self.__get_images_num = get_images_num if get_images_num is not None else len(self.__image_pathes)
        self.__image_loader = image_loader
        self.__cur_index = 0
        self.__buffer_is_ready = False
        self.__buffer_load_thread = None
        self.__images_buffers = [None, None]
        self.__processes_num = 1
        self.__swap_buffers()

    def load(self, path: str):
        """
        Load image by url
        :param path: path to image
        :return: image object
        """
        self.__image_loader.load(path)

    def set_processes_num(self, processes_num):
        self.__processes_num = processes_num

    def set_iterations_num(self, get_images_num):
        self.__get_images_num = get_images_num

    def __getitem__(self, index):
        if (index - 1) * self.__batch_size >= (
        len(self.__image_pathes) if self.__get_images_num is None else self.__get_images_num):
            raise IndexError
        if not self.__buffer_is_ready:
            self.__buffer_load_thread.join()
        self.__swap_buffers()
        return self.__images_buffers[0]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__images_buffers = [None, None]
        self.__buffer_is_ready = False

    def __load_buffer(self):
        def form_thread_data():
            def get_data(idx_number: int):
                indices = np.roll(np.arange(len(self.__image_pathes)), -self.__cur_index)[0: idx_number]
                return [[self.__image_loader, self.__image_pathes[idx]] for idx in indices]

            if (self.__cur_index + self.__batch_size) < self.__get_images_num:
                return get_data(self.__batch_size)
            elif self.__cur_index < self.__get_images_num:
                return get_data(self.__get_images_num - self.__cur_index)
            else:
                return None

        threads_data = form_thread_data()

        if threads_data is None:
            return []
        if len(threads_data) == 1:
            self.__cur_index += 1
            return [load_image(threads_data[0])]

        if self.__processes_num > 1:
            pool = Pool(self.__processes_num)
            try:
                new_buffer = pool.map(load_image, threads_data)
                pool.close()
            except:
                print(len(threads_data))
                print(threads_data)
                self.__cur_index += self.__batch_size
                return []
        else:
            new_buffer = [load_image(thread_data) for thread_data in threads_data]

        self.__cur_index += self.__batch_size
        return new_buffer

    def __swap_buffers(self):
        def process():
            self.__images_buffers.append(self.__load_buffer())
            self.__buffer_is_ready = True

        del self.__images_buffers[0]
        self.__buffer_is_ready = False
        self.__buffer_load_thread = Thread(target=process)
        self.__buffer_load_thread.start()
