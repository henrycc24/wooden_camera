#ifndef _LWIPOPTS_H
#define _LWIPOPTS_H

// Common settings used in most pico_w wifi examples
#define NO_SYS                      1
#define LWIP_SOCKET                 0
#define LWIP_COMPAT_SOCKETS         0
#define LWIP_CORE_OS                0
#define LWIP_NETCONN                0
#define LWIP_DNS                    1
#define LWIP_TCP                    1
#define LWIP_IGMP                   1
#define LWIP_UDP                    1
#define LWIP_ICMP                   1
#define LWIP_DHCP                   1
#define LWIP_IPV4                   1
#define LWIP_TCP_KEEPALIVE          1
#define LWIP_NETIF_TX_SINGLE_PBUF   1
#define LWIP_DHCP_DOES_ARP_CHECK    0
#define LWIP_IGMP                   1

// Memory sizing
#define MEM_ALIGNMENT               4
#define MEM_SIZE                    4000
#define MEMP_NUM_TCP_SEG            32
#define MEMP_NUM_ARP_QUEUE          10
#define PBUF_POOL_SIZE              24
#define LWIP_ARP                    1
#define LWIP_ETHERNET               1
#define LWIP_NETIF_STATUS_CALLBACK  1
#define LWIP_NETIF_LINK_CALLBACK    1
#define LWIP_NETIF_HOSTNAME         1
#define LWIP_NETIF_API              0
#define HW_CHECKSUM                 1
#define LWIP_CHECKSUM_CTRL_PER_NETIF 1

#endif
