/*
 * Copyright (c) 2001-2004 Twisted Matrix Laboratories.
 * See LICENSE for details.

 * 
 */
/* cReactorBuffer.c - a simple read/write buffer. */

/* includes */
#include "cReactor.h"

struct _cReactorBuffer
{
    unsigned char *     memory;
    unsigned int        memory_size;
    unsigned char *     read_ptr;
    unsigned char *     write_ptr;
};


cReactorBuffer *
cReactorBuffer_New(unsigned int size)
{
    cReactorBuffer *buf;

    buf = (cReactorBuffer *)malloc(sizeof(cReactorBuffer));
    buf->memory         = (unsigned char *)malloc(size);
    buf->memory_size    = size;
    buf->read_ptr       = buf->memory;
    buf->write_ptr      = buf->memory;

    return buf;
}


void
cReactorBuffer_Destroy(cReactorBuffer *buffer)
{
    if (buffer)
    {
        free(buffer->memory);
        free(buffer);
    }
}


void
cReactorBuffer_Write(cReactorBuffer *buffer, const void *data, unsigned int size)
{
    unsigned int used;
    unsigned int avail;
    unsigned int pre_read;
    unsigned int new_size;
    unsigned char *new_mem;

    /* Determine how much is used. */
    used = buffer->write_ptr - buffer->read_ptr;

    /* Determine how much space is currently available. */
    avail = (buffer->memory + buffer->memory_size) - buffer->write_ptr;

    /* Check if we do not have enough space to write. */
    if (avail < size)
    {
        /* If there is enough space between the start of the memory block and the
         * read pointer we can slide the buffer back towards the memory block
         * start.
         */
        pre_read = buffer->read_ptr - buffer->memory;
        if ((avail + pre_read) >= size)
        {
            /* Sliding will give us the space. */
            memmove(buffer->memory, buffer->read_ptr, used);
            buffer->read_ptr        = buffer->memory;
            buffer->write_ptr      -= pre_read;
        }
        else
        {
            /* We have to allocate a new buffer. */
            new_size  = (buffer->memory_size * 2) + size;
            new_mem   = (unsigned char *)malloc(new_size);
            memcpy(new_mem, buffer->read_ptr, used); 

            buffer->write_ptr   = new_mem + used;
            buffer->read_ptr    = new_mem;
            buffer->memory_size = new_size;
    
            free(buffer->memory);
            buffer->memory = new_mem;
        }
    }

    /* Write. */
    memcpy(buffer->write_ptr, data, size);
    buffer->write_ptr += size;

}


unsigned int
cReactorBuffer_DataAvailable(cReactorBuffer *buffer)
{
    /* Allow NULL buffers. */
    return (buffer 
            ? (buffer->write_ptr - buffer->read_ptr)
            : 0);
}


const unsigned char *
cReactorBuffer_GetPtr(cReactorBuffer *buffer)
{
    return buffer->read_ptr;
}

void
cReactorBuffer_Seek(cReactorBuffer *buffer, unsigned int forward)
{
    unsigned int avail;

    avail = (buffer->write_ptr - buffer->read_ptr);
    if (forward >= avail)
    {
        buffer->write_ptr   = buffer->memory;
        buffer->read_ptr    = buffer->memory;
    }
    else
    {
        buffer->read_ptr += forward;
    }
}

/* vim: set sts=4 sw=4: */
