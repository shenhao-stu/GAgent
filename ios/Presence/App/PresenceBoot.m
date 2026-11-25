// Presence installs itself. With its sources in the app target the status UI starts when the app has
// launched; without them the app is exactly what it was. No file of the app calls into Presence.
#import <UIKit/UIKit.h>
#import <objc/message.h>

@interface GAPresenceBoot : NSObject
@end

@implementation GAPresenceBoot

+ (void)load {
    [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidFinishLaunchingNotification
                                                    object:nil
                                                     queue:NSOperationQueue.mainQueue
                                                usingBlock:^(NSNotification *note) {
        Class entry = NSClassFromString(@"GAPresenceEntry");
        SEL start = NSSelectorFromString(@"start");
        if ([entry respondsToSelector:start]) ((void (*)(id, SEL))objc_msgSend)(entry, start);
    }];
}

@end
