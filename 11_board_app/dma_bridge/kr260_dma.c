// SPDX-License-Identifier: GPL-2.0
// Keep an imported CMA DMA-BUF mapped for PL until its owner closes this fd.
#include <linux/module.h>
#include <linux/device.h>
#include <linux/dma-buf.h>
#include <linux/dma-mapping.h>
#include <linux/miscdevice.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>

struct kr260_request { __s32 fd; __u32 reserved; __u64 address; __u64 size; };
#define KR260_MAP _IOWR('K', 0, struct kr260_request)
struct mapping {
    struct dma_buf *buffer;
    struct dma_buf_attachment *attachment;
    struct sg_table *table;
    struct mutex mutex;
};
static struct device *dma_device;
static u64 address_mask = DMA_BIT_MASK(32);

static void release_mapping(struct mapping *m)
{
    if (m->table)
        dma_buf_unmap_attachment_unlocked(m->attachment, m->table, DMA_BIDIRECTIONAL);
    if (m->attachment)
        dma_buf_detach(m->buffer, m->attachment);
    if (m->buffer)
        dma_buf_put(m->buffer);
    m->table = NULL;
    m->attachment = NULL;
    m->buffer = NULL;
}

static int bridge_open(struct inode *inode, struct file *file)
{
    struct mapping *m = kzalloc(sizeof(*m), GFP_KERNEL);
    if (!m)
        return -ENOMEM;
    mutex_init(&m->mutex);
    file->private_data = m;
    return 0;
}

static int bridge_release(struct inode *inode, struct file *file)
{
    struct mapping *m = file->private_data;
    release_mapping(m);
    kfree(m);
    return 0;
}

static long bridge_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    struct mapping *m = file->private_data;
    struct kr260_request req;
    long ret = 0;
    if (cmd != KR260_MAP)
        return -ENOTTY;
    if (copy_from_user(&req, (void __user *)arg, sizeof(req)))
        return -EFAULT;
    if (req.reserved)
        return -EINVAL;
    mutex_lock(&m->mutex);
    if (m->buffer) { ret = -EBUSY; goto out; }
    m->buffer = dma_buf_get(req.fd);
    if (IS_ERR(m->buffer)) { ret = PTR_ERR(m->buffer); m->buffer = NULL; goto out; }
    if (strcmp(m->buffer->exp_name, "reserved")) { ret = -EINVAL; goto fail; }
    m->attachment = dma_buf_attach(m->buffer, dma_device);
    if (IS_ERR(m->attachment)) { ret = PTR_ERR(m->attachment); m->attachment = NULL; goto fail; }
    m->table = dma_buf_map_attachment_unlocked(m->attachment, DMA_BIDIRECTIONAL);
    if (IS_ERR(m->table)) { ret = PTR_ERR(m->table); m->table = NULL; goto fail; }
    if (m->table->nents != 1) { ret = -ERANGE; goto fail; }
    req.address = sg_dma_address(m->table->sgl);
    req.size = m->buffer->size;
    if (sg_dma_len(m->table->sgl) < req.size || req.address + req.size > 0x80000000ULL) {
        ret = -ERANGE; goto fail;
    }
    if (copy_to_user((void __user *)arg, &req, sizeof(req))) { ret = -EFAULT; goto fail; }
    goto out;
fail:
    release_mapping(m);
out:
    mutex_unlock(&m->mutex);
    return ret;
}

static const struct file_operations bridge_fops = {
    .owner = THIS_MODULE, .open = bridge_open, .release = bridge_release,
    .unlocked_ioctl = bridge_ioctl, .llseek = no_llseek,
};
static struct miscdevice bridge = {
    .minor = MISC_DYNAMIC_MINOR, .name = "kr260_dma", .fops = &bridge_fops, .mode = 0600,
};

static int __init bridge_init(void)
{
    int ret;
    dma_device = root_device_register("kr260-adas-dma");
    if (IS_ERR(dma_device))
        return PTR_ERR(dma_device);
    dma_device->dma_mask = &address_mask;
    ret = dma_set_mask_and_coherent(dma_device, DMA_BIT_MASK(32));
    if (ret)
        goto fail;
    ret = misc_register(&bridge);
    if (ret)
        goto fail;
    return 0;
fail:
    root_device_unregister(dma_device);
    return ret;
}
static void __exit bridge_exit(void)
{
    misc_deregister(&bridge);
    root_device_unregister(dma_device);
}
module_init(bridge_init);
module_exit(bridge_exit);
MODULE_LICENSE("GPL");
MODULE_IMPORT_NS(DMA_BUF);
MODULE_DESCRIPTION("KR260 CMA DMA-BUF mapping bridge for direct HP0/HP1 DDR access");
