#include "lvgl.h"
#include <errno.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static const char *modes[] = {"page","batch","multipass","receipt"};
static const char *titles[] = {"Page","Batch","Multipass","Receipt"};
static const char *hints[] = {"One PDF per side","One PDF per stack","Combine stacks","Thermal paper"};
enum {BG=0x10212B, CARD=0x203541, LINE=0x38515E, INK=0xF5F8F7,
      MUTED=0xAEC3C9, MINT=0x7DE5C3, ACTIVE=0x184B46};
static lv_obj_t *tiles[4], *marks[4], *scan, *scan_label, *finish, *scanner, *task, *indicator;
static int ipc, pending, waiting, ack, french, percent=-1;
static lv_obj_t *track, *fill, *counter;
static lv_font_t fonts[4];

static int load_fonts(void) {
    const lv_font_t *base[] = {&lv_font_montserrat_14, &lv_font_montserrat_16,
                               &lv_font_montserrat_20, &lv_font_montserrat_24};
    const int size[] = {14,16,20,24};
    int fd=open("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", O_RDONLY);
    struct stat st;
    if(fd<0 || fstat(fd,&st)<0) return 0;
    void *data=mmap(NULL,st.st_size,PROT_READ,MAP_PRIVATE,fd,0);
    close(fd);
    if(data==MAP_FAILED) return 0;
    for(int i=0;i<4;i++) {
        fonts[i]=*base[i];
        fonts[i].fallback=lv_tiny_ttf_create_data_ex(data,st.st_size,size[i],LV_FONT_KERNING_NORMAL,16);
        if(!fonts[i].fallback) return 0;
    }
    return 1;
}
static const char *env(const char *name,const char *fallback) {
    const char *v=getenv(name); return v && *v?v:fallback;
}
static void color(lv_obj_t *o, int rgb) {
    lv_obj_set_style_bg_color(o,lv_color_hex(rgb),0);
}
static lv_obj_t *box(lv_obj_t *parent,int x,int y,int w,int h,int bg,int radius) {
    lv_obj_t *o=lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_remove_flag(o,LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_size(o,w,h); lv_obj_set_pos(o,x,y);
    lv_obj_set_style_bg_opa(o,LV_OPA_COVER,0); color(o,bg);
    lv_obj_set_style_radius(o,radius,0); return o;
}
static lv_obj_t *label(lv_obj_t *o,int x,int y,const char *text,const lv_font_t *font,int rgb) {
    lv_obj_t *l=lv_label_create(o);
    lv_label_set_text(l,text); lv_obj_set_pos(l,x,y);
    lv_obj_set_style_text_font(l,font,0); lv_obj_set_style_text_color(l,lv_color_hex(rgb),0);
    return l;
}
static void clicked(lv_event_t *e) {
    const char *action=lv_event_get_user_data(e);
    if(pending) return;
    if(!strcmp(action,"start") && waiting) action="next";
    if(send(ipc,action,strlen(action),MSG_NOSIGNAL)>0) pending=1;
}
static void button(lv_obj_t *o,const char *action) {
    lv_obj_add_flag(o,LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(o,clicked,LV_EVENT_CLICKED,(void*)action);
    lv_obj_set_style_bg_color(o,lv_color_hex(0x42685F),LV_STATE_PRESSED);
}
static void enabled(lv_obj_t *o,int yes) {
    if(yes) lv_obj_remove_state(o,LV_STATE_DISABLED); else lv_obj_add_state(o,LV_STATE_DISABLED);
}
static void build(void) {
    const char *fr_titles[]={"Page","Lot","Multipassage","Ticket"};
    const char *fr_hints[]={"Un PDF par face","Un PDF pour la pile","Réunir plusieurs piles","Ticket de caisse"};
    lv_obj_t *s=lv_screen_active();color(s,BG);
    label(s,14,7,"ScanStation",&fonts[3],INK);
    indicator=box(s,449,17,10,10,MUTED,5);
    for(int i=0;i<4;i++) {
        lv_obj_t *o=tiles[i]=box(s,12+232*(i%2),47+65*(i/2),224,58,CARD,8);
        lv_obj_set_style_border_width(o,1,0); lv_obj_set_style_border_color(o,lv_color_hex(LINE),0);
        label(o,12,5,french?fr_titles[i]:titles[i],&fonts[2],INK);
        label(o,12,31,french?fr_hints[i]:hints[i],&fonts[0],MUTED);
        marks[i]=label(o,191,10,LV_SYMBOL_OK,&fonts[1],MINT);
        lv_obj_add_flag(marks[i],LV_OBJ_FLAG_HIDDEN);
        button(o,modes[i]);
    }
    scan=box(s,12,181,456,49,MINT,8);button(scan,"start");
    scan_label=label(scan,0,0,french?"Numériser":"Scan",&fonts[3],BG);
    lv_obj_center(scan_label);
    finish=box(s,300,181,168,49,CARD,8);button(finish,"finish");
    lv_obj_center(label(finish,0,0,french?"Terminer le PDF":"Finish PDF",&fonts[2],INK));
    lv_obj_add_flag(finish,LV_OBJ_FLAG_HIDDEN);
    box(s,0,242,480,1,LINE,0);
    scanner=label(s,14,244,french?"Connexion":"Connecting",&fonts[2],INK);
    task=label(s,14,274,french?"Démarrage":"Starting controller",&fonts[1],MUTED);
    counter=label(s,396,274,"",&fonts[1],MINT);
    lv_obj_set_width(counter,70);lv_obj_set_style_text_align(counter,LV_TEXT_ALIGN_RIGHT,0);
    track=box(s,14,301,452,8,LINE,4);
    fill=box(track,0,0,1,8,MINT,4);
    lv_obj_set_style_pad_all(track,0,0);
    lv_obj_add_flag(fill,LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_width(task,379); lv_label_set_long_mode(task,LV_LABEL_LONG_DOT);
    for(int i=0;i<4;i++) enabled(tiles[i],0);
    enabled(scan,0);
}
static void apply(char *packet) {
    char *f[9];
    for(int i=0;i<9;i++) if(!(f[i]=strsep(&packet,"\t"))) return;
    int new_ack=atoi(f[0]);
    if(new_ack!=ack) { ack=new_ack; pending=0; }
    int selectable=atoi(f[2]), can_scan=atoi(f[3]); waiting=atoi(f[4]);
    for(int i=0;i<4;i++) {
        int on=!strcmp(modes[i],f[1]);
        color(tiles[i],on?ACTIVE:CARD);
        lv_obj_set_style_border_color(tiles[i],lv_color_hex(on?MINT:LINE),0);
        if(on) lv_obj_remove_flag(marks[i],LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(marks[i],LV_OBJ_FLAG_HIDDEN);
        enabled(tiles[i],selectable);
    }
    if(waiting) lv_obj_remove_flag(finish,LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(finish,LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_width(scan,waiting?280:456); enabled(scan,can_scan);
    color(scan,can_scan?MINT:0x718E93);
    lv_label_set_text(scan_label,waiting?(french?"Pile suivante":"Scan next stack"):(french?"Numériser":"Scan"));lv_obj_center(scan_label);
    lv_label_set_text(scanner,f[5]);lv_label_set_text(task,f[6]);
    color(indicator,atoi(f[8])?MINT:0xFFB777);
    percent=atoi(f[7]);
    if(percent>=0) lv_label_set_text_fmt(counter,"%d %%",percent);
    else lv_label_set_text(counter,"");
    if(percent==0 || percent==-1) lv_obj_add_flag(fill,LV_OBJ_FLAG_HIDDEN);
    else {
        lv_obj_remove_flag(fill,LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_width(fill,percent==-2?70:452*percent/100);
        if(percent!=-2) lv_obj_set_x(fill,0);
    }
}
int main(int argc,char **argv) {
    if(argc!=3) return 2;
    french=!strcmp(argv[2],"fr");
    ipc=atoi(argv[1]);
    lv_init();
    lv_display_t *display=lv_linux_fbdev_create();
    lv_linux_fbdev_set_file(display,env("SCANSTATION_FB","/dev/fb0"));
    if(lv_display_get_horizontal_resolution(display)!=480 || lv_display_get_vertical_resolution(display)!=320) {
        fprintf(stderr,"ScanStation requires a 480x320 framebuffer\n");return 1;
    }
    lv_indev_t *input=lv_evdev_create(LV_INDEV_TYPE_POINTER,env("SCANSTATION_TOUCH","/dev/input/by-path/platform-fe204000.spi-cs-1-event"));
    if(!input) return 1;
    lv_evdev_set_swap_axes(input,atoi(env("SCANSTATION_SWAP","0")));
    const char *cal=getenv("SCANSTATION_CALIBRATION");
    int x1,y1,x2,y2;
    if(cal && sscanf(cal,"%d,%d,%d,%d",&x1,&y1,&x2,&y2)==4)
        lv_evdev_set_calibration(input,x1,y1,x2,y2);
    if(!load_fonts()) return 1;
    build();
    uint32_t last_move=0;
    for(;;) {
        char packet[2048];
        ssize_t n=recv(ipc,packet,sizeof(packet)-1,MSG_DONTWAIT);
        if(n>0) { packet[n]=0; apply(packet); }
        else if(n==0 || (errno!=EAGAIN && errno!=EWOULDBLOCK && errno!=EINTR)) return 1;
        if(percent==-2 && lv_tick_elaps(last_move)>=80) {
            last_move=lv_tick_get();
            unsigned phase=(last_move/8)%764;
            lv_obj_set_x(fill,phase<=382?phase:764-phase);
        }
        uint32_t delay=lv_timer_handler();
        usleep((delay>20?20:(delay?delay:1))*1000);
    }
}
